#!/usr/bin/env python3
"""Run bounded Phase 9 benchmark smoke campaigns and write canonical JSON."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, selectors, subprocess, sys, time
from pathlib import Path
from statistics import mean, median, pstdev

SCHEMA_VERSION="1.0.0"; FIXTURE_SET_VERSION="1.0.0"; HARNESS_VERSION="1.0.0"
OUTPUT_LIMIT=256*1024; STDERR_LIMIT=64*1024; PROCESS_TIMEOUT=10.0; MAX_SAMPLES=15
def fail(message: str) -> None: raise RuntimeError(message)
def canonical(value: object) -> str: return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=True)+"\n"
def bounded_run(command: list[str], data: bytes) -> bytes:
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(data); process.stdin.close()
    selector=selectors.DefaultSelector(); buffers={process.stdout:bytearray(),process.stderr:bytearray()}
    for stream in buffers: os.set_blocking(stream.fileno(),False); selector.register(stream,selectors.EVENT_READ)
    deadline=time.monotonic()+PROCESS_TIMEOUT
    try:
      while selector.get_map() or process.poll() is None:
        remaining=deadline-time.monotonic()
        if remaining<=0: fail("subprocess lifetime limit exceeded")
        for key,_ in selector.select(remaining):
          stream=key.fileobj; chunk=os.read(stream.fileno(),8192)
          if not chunk: selector.unregister(stream); stream.close(); continue
          buffers[stream].extend(chunk)
          if len(buffers[stream]) > (OUTPUT_LIMIT if stream is process.stdout else STDERR_LIMIT): fail("subprocess output byte limit exceeded")
      if process.wait(timeout=0.1)!=0: fail("benchmark subprocess failed")
      if buffers[process.stderr]: fail("strict benchmark subprocess wrote standard error")
      return bytes(buffers[process.stdout])
    except BaseException:
      process.kill(); process.wait(); raise
    finally: selector.close()
def summary(case_id: str, samples: list[float], input_bytes: int, operations: int, concurrency: int=1) -> dict[str,object]:
    if not samples or len(samples)>MAX_SAMPLES: fail("invalid sample count")
    ordered=sorted(samples)
    return {"caseId":case_id,"unit":"nanoseconds_per_operation","inputBytes":input_bytes,"operationCount":operations,"concurrency":concurrency,"timeoutMilliseconds":int(PROCESS_TIMEOUT*1000),"warmupIterations":1,"sampleCount":len(samples),"originalSampleCount":len(samples),"retainedSampleCount":len(samples),"excludedSampleCount":0,"exclusionClasses":[],"rawSamples":samples,"minimum":ordered[0],"maximum":ordered[-1],"median":median(samples),"p95":ordered[min(len(samples)-1,int(len(samples)*.95))],"mean":mean(samples),"standardDeviation":pstdev(samples),"validationInTimedRegion":True}
def requests(configured: bool, root: Path, policy_directory: Path) -> tuple[list[str],bytes,int]:
    messages=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"phase-9","version":"1"}}},{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}]
    command=[]
    if configured:
      policy_directory.mkdir(parents=True,exist_ok=True); policy=policy_directory/"benchmark-policy.json"; policy.write_text(canonical({"version":2,"roots":[{"name":"fixtures","path":str(root),"maxFileBytes":65536}],"processes":[{"name":"server","pid":"self"}]}),encoding="utf-8")
      command=["--policy-config",str(policy)]
      calls=[("logs.search",{"root":"fixtures","path":"log.txt","query":"needle","caseSensitive":True,"maxMatches":10}),("logs.tail",{"root":"fixtures","path":"log.txt","maxLines":2}),("elf.inspect",{"root":"fixtures","path":"minimal.elf"}),("proc.memory",{"process":"server"})]
      for index,(name,args) in enumerate(calls,10): messages.append({"jsonrpc":"2.0","id":index,"method":"tools/call","params":{"name":name,"arguments":args}})
    return command, ("".join(canonical(message) for message in messages)).encode(), len(messages)
def e2e_case(case_id: str, server: Path, configured: bool, fixtures: Path, policy_directory: Path) -> dict[str,object]:
    command, payload, operations=requests(configured,fixtures,policy_directory); samples=[]
    for _ in range(1): bounded_run([str(server),*command],payload)
    for _ in range(5):
      started=time.monotonic_ns(); output=bounded_run([str(server),*command],payload)
      responses=[json.loads(line) for line in output.decode().splitlines()]
      expected=({1,2} | set(range(10,14))) if configured else {1,2}
      if {response.get("id") for response in responses} != expected: fail("response correlation failed")
      samples.append((time.monotonic_ns()-started)/operations)
    return summary(case_id,samples,len(payload),operations,4 if configured else 1)
def metadata(server: Path) -> dict[str,object]:
    def value(v: object) -> dict[str,object]: return {"available":True,"value":v}
    return {"repositoryCommit":value(subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()),"dirtyWorktree":value(bool(subprocess.check_output(["git","status","--porcelain"],text=True).strip())),"benchmarkExecutableSha256":value(hashlib.sha256(server.read_bytes()).hexdigest()),"operatingSystem":value(platform.platform()),"kernel":value(platform.release()),"logicalCpuCount":value(os.cpu_count()),"pageSize":value(os.sysconf("SC_PAGE_SIZE")),"monotonicClock":value("time.monotonic_ns"),"harnessVersion":value(HARNESS_VERSION),"schemaVersion":value(SCHEMA_VERSION),"fixtureSetVersion":value(FIXTURE_SET_VERSION),"noiseControls":{"cpuAffinity":"unavailable","governor":"unavailable","turbo":"unavailable","idleSystem":"not-applied"}}
def main() -> int:
 p=argparse.ArgumentParser(); p.add_argument("--benchmark",type=Path,required=True); p.add_argument("--server",type=Path,required=True); p.add_argument("--fixtures",type=Path,required=True); p.add_argument("--output",type=Path,default=Path("build/benchmark-report.json")); args=p.parse_args()
 if args.output.exists(): args.output.unlink()
 if not args.fixtures.is_dir(): fail("fixture directory missing")
 component=json.loads(bounded_run([str(args.benchmark),str(args.fixtures)],b"").decode())
 cases=component["cases"]+[e2e_case("e2e.unconfigured.lifecycle_tools_list",args.server,False,args.fixtures,args.output.parent),e2e_case("e2e.configured.all_tools_concurrent",args.server,True,args.fixtures,args.output.parent)]
 report={"schemaVersion":SCHEMA_VERSION,"fixtureSetVersion":FIXTURE_SET_VERSION,"harnessVersion":HARNESS_VERSION,"framework":component["framework"],"outlierPolicy":"All valid samples are retained; no automatic outlier filter is applied.","metadata":metadata(args.benchmark),"cases":cases,"comparisonNotes":["SAX plus DOM versus DOM alone is measured only on equivalent valid protocol input. Reduced-control references are measurement-only and unsafe as a deployment recommendation."],"complete":True}
 encoded=canonical(report).encode();
 if len(encoded)>OUTPUT_LIMIT: fail("report byte limit exceeded")
 args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_bytes(encoded); return 0
if __name__=="__main__":
 try: raise SystemExit(main())
 except Exception as error: print(f"benchmark failure: {error}",file=sys.stderr); raise SystemExit(1)
