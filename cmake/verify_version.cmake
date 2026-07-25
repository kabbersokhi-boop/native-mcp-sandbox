if(NOT DEFINED NMS_EXECUTABLE OR NOT DEFINED NMS_EXPECTED)
  message(FATAL_ERROR "NMS_EXECUTABLE and NMS_EXPECTED are required")
endif()

execute_process(
  COMMAND "${NMS_EXECUTABLE}" --version
  RESULT_VARIABLE result
  OUTPUT_VARIABLE output
  ERROR_VARIABLE error
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT result EQUAL 0)
  message(FATAL_ERROR "--version exited with ${result}: ${error}")
endif()
if(NOT output STREQUAL NMS_EXPECTED)
  message(FATAL_ERROR "unexpected --version output: [${output}]")
endif()
