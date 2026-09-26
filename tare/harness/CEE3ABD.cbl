      *HARNESS: stands in for the Language Environment service CEE3ABD,
      * which on z/OS abends the enclave (user abend U<abcode>). Off the
      * mainframe the run ends here with RETURN-CODE = abend code (a
      * POSIX shell sees it modulo 256). Called with no parameters,
      * there is no abend code and the run ends with RETURN-CODE 16.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEE3ABD.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-ABCODE                  PIC S9(9) BINARY.
       01  LS-TIMING                  PIC S9(9) BINARY.
       PROCEDURE DIVISION USING LS-ABCODE LS-TIMING.
           IF ADDRESS OF LS-ABCODE = NULL
               DISPLAY 'CEE3ABD: ABEND (called without an abend code)'
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF
           DISPLAY 'CEE3ABD: ABEND U' LS-ABCODE ' TIMING ' LS-TIMING
           MOVE LS-ABCODE TO RETURN-CODE
           STOP RUN.
