      *HARNESS: our code (MIT), not part of the CMS sources.
      *
      * Batch driver for CMS's FY2021.0 Hospice Pricer. It plays the part
      * of the wrapper JCL ships but does not (HOSOP210 in TESTJCL): it
      * loads the wage-index and provider tables that HOSDR210 expects,
      * reads each 315-byte BILLFILE record (copybook BILL-315-DATA,
      * HOSPR210.cbl:246), CALLs the unmodified HOSDR210, and writes the
      * record back to RATEFILE with the pricer's returned fields filled
      * in. The DD names are the ones TESTJCL uses (BILLFILE, CBSAFILE,
      * PROVFILE); each is assigned from the environment variable of the
      * same name, which is how Tare passes a job step's DDs.
      *
      * MSAFILE is not read: the FY2021 release ships CBSA2021 only, and
      * every claim priced here has a service date in FY2021, which
      * HOSDR210 prices from the CBSA table (HOSDR210.cbl:0525, :0575).
      * The MSA table is left empty, so a claim dated before 2008 would
      * not find a wage index; the input here holds no such claim.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HOSRUN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CBSAFILE ASSIGN TO CBSAFILE
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS IS CBSA-FS.
           SELECT PROVFILE ASSIGN TO PROVFILE
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS IS PROV-FS.
           SELECT BILLFILE ASSIGN TO BILLFILE
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS IS BILL-FS.
           SELECT RATEFILE ASSIGN TO RATEFILE
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS IS RATE-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CBSAFILE.
       01  CBSA-REC.
           05  CR-CBSA        PIC 9(05).
           05  FILLER         PIC X.
           05  CR-EFFDTE      PIC X(08).
           05  FILLER         PIC X.
           05  CR-WI          PIC 9(02)V9(04).
           05  FILLER         PIC X(59).
       FD  PROVFILE.
       01  PROV-REC.
           05  PR-1           PIC X(80).
           05  PR-2           PIC X(80).
           05  PR-3           PIC X(80).
       FD  BILLFILE.
       01  BILL-IN            PIC X(315).
       FD  RATEFILE.
       01  BILL-OUT           PIC X(315).
       WORKING-STORAGE SECTION.
       01  HOSDR210           PIC X(08) VALUE 'HOSDR210'.
       01  EOF-SW             PIC 9 VALUE 0.
       01  CBSA-FS            PIC XX.
       01  PROV-FS            PIC XX.
       01  BILL-FS            PIC XX.
       01  RATE-FS            PIC XX.
       01  N-CBSA             PIC 9(05) VALUE 0.
       01  N-PROV             PIC 9(05) VALUE 0.
       01  N-BILL             PIC 9(09) VALUE 0.
       01  BILL-315-DATA      PIC X(315).
       01  PROV-TABLE.
           02  PROV-ENTRIES OCCURS 2400.
               10  PROV-DATA1 PIC X(80).
       01  PROV-DATA-2.
           02  PROV-DATA2     PIC X(80) OCCURS 2400.
       01  PROV-DATA-3.
           02  PROV-DATA3     PIC X(80) OCCURS 2400.
       01  MSA-WI-TABLE.
           05  M-MSA-DATA OCCURS 4000.
               10  MSA-MSA-LUGAR PIC X(05).
               10  MSA-EFFDTE    PIC X(08).
               10  MSA-WAGE-IND  PIC S9(02)V9(04).
       01  CBSA-WI-TABLE.
           05  M-CBSA-DATA OCCURS 9000.
               10  M-CBSA         PIC 9(05).
               10  M-CBSA-EFFDTE  PIC X(08).
               10  M-CBSA-WAGE-IND PIC S9(02)V9(04).
       PROCEDURE DIVISION.
           INITIALIZE MSA-WI-TABLE CBSA-WI-TABLE.
           MOVE ALL '9' TO PROV-TABLE.
           OPEN INPUT CBSAFILE
           IF CBSA-FS NOT = '00'
               DISPLAY 'HOSRUN: OPEN CBSAFILE FILE STATUS ' CBSA-FS
               MOVE 12 TO RETURN-CODE
               STOP RUN
           END-IF
           MOVE 0 TO EOF-SW
           PERFORM UNTIL EOF-SW = 1
               READ CBSAFILE AT END MOVE 1 TO EOF-SW
               NOT AT END
                   ADD 1 TO N-CBSA
                   IF N-CBSA > 9000
                       DISPLAY 'HOSRUN: CBSAFILE holds more than 9000 '
                               'rows, the CBSA-WI-TABLE size'
                       MOVE 12 TO RETURN-CODE
                       STOP RUN
                   END-IF
                   MOVE CR-CBSA   TO M-CBSA (N-CBSA)
                   MOVE CR-EFFDTE TO M-CBSA-EFFDTE (N-CBSA)
                   MOVE CR-WI     TO M-CBSA-WAGE-IND (N-CBSA)
               END-READ
           END-PERFORM.
           CLOSE CBSAFILE
           MOVE 0 TO EOF-SW
           OPEN INPUT PROVFILE
           IF PROV-FS NOT = '00'
               DISPLAY 'HOSRUN: OPEN PROVFILE FILE STATUS ' PROV-FS
               MOVE 12 TO RETURN-CODE
               STOP RUN
           END-IF
           PERFORM UNTIL EOF-SW = 1
               READ PROVFILE AT END MOVE 1 TO EOF-SW
               NOT AT END
                   ADD 1 TO N-PROV
                   IF N-PROV > 2400
                       DISPLAY 'HOSRUN: PROVFILE holds more than 2400 '
                               'rows, the PROV-TABLE size'
                       MOVE 12 TO RETURN-CODE
                       STOP RUN
                   END-IF
                   MOVE PR-1 TO PROV-DATA1 (N-PROV)
                   MOVE PR-2 TO PROV-DATA2 (N-PROV)
                   MOVE PR-3 TO PROV-DATA3 (N-PROV)
               END-READ
           END-PERFORM.
           CLOSE PROVFILE
           MOVE 0 TO EOF-SW
           OPEN INPUT BILLFILE OUTPUT RATEFILE
           IF BILL-FS NOT = '00' OR RATE-FS NOT = '00'
               DISPLAY 'HOSRUN: OPEN BILLFILE ' BILL-FS
                       ' RATEFILE ' RATE-FS
               MOVE 12 TO RETURN-CODE
               STOP RUN
           END-IF
           PERFORM UNTIL EOF-SW = 1
               READ BILLFILE AT END MOVE 1 TO EOF-SW
               NOT AT END
                   ADD 1 TO N-BILL
                   MOVE BILL-IN TO BILL-315-DATA
                   CALL HOSDR210 USING BILL-315-DATA PROV-TABLE
                        PROV-DATA-2 PROV-DATA-3 MSA-WI-TABLE
                        CBSA-WI-TABLE
                   MOVE BILL-315-DATA TO BILL-OUT
                   WRITE BILL-OUT
               END-READ
           END-PERFORM.
           CLOSE BILLFILE RATEFILE.
           DISPLAY 'HOSRUN CBSA=' N-CBSA ' PROV=' N-PROV
                   ' BILLS=' N-BILL.
           STOP RUN.
