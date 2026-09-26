      *HARNESS: our code (MIT), not part of the DGFiP sources.
      * Stands in for the job that loads the rate file TAUDIS. It
      * writes the three records EFITAUX2 reads for each commune, laid
      * out with the ORIGINAL copybooks T800 + T84D/T84C/T84R, so each
      * rate lands at the offset EFITAUX2 reads it from:
      *   direction  key DIR + LOW-VALUES           PTBDEP PTBTAS
      *   commune    key DIR + COM + LOW-VALUES     GCOVEF = 'V'
      *   IFP        key DIR + COM + IFP + PER      commune, syndicate,
      *              EPCI, TSE 1 and 2, GEMAPI and household-waste rates
      * Only built-property rates are loaded; every other rate is zero.
      * DD RATES: fixed 200-byte records, fields separated by ';':
      * dir;com;ifp;per;PTBDEP;PTBTAS;PTBCOM;PTBSYN;PTBCU;PTBTSN1;
      * PTBTSN2;PTBGEM;PBBOMP;PBBOMA;PBBOMB;PBBOMC;PBBOMD;PBBOME
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOADTAU.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAUDIS ASSIGN TO TAUDIS
                  ORGANIZATION INDEXED
                  ACCESS MODE DYNAMIC
                  RECORD KEY TAUDIS-CLE
                  FILE STATUS TAUDIS-FS.
           SELECT RATES ASSIGN TO RATES
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS RATES-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TAUDIS
           RECORD CONTAINS 3000 CHARACTERS.
       01  TAUDIS-DATA.
           02 TAUDIS-CLE             PIC X(12).
           02 TAUDIS-SUITE           PIC X(2988).
       FD  RATES
           RECORD CONTAINS 200 CHARACTERS.
       01  RATE-REC                  PIC X(200).
       WORKING-STORAGE SECTION.
       01  TAUDIS-FS                 PIC XX.
       01  RATES-FS                  PIC XX.
       01  EOF-SW                    PIC X VALUE 'N'.
       01  NDIR                      PIC 9(7) VALUE 0.
       01  NCOM                      PIC 9(7) VALUE 0.
       01  NIFP                      PIC 9(7) VALUE 0.
       01  NERR                      PIC 9(7) VALUE 0.
       01  TOK-TAB.
           05 TOK                    PIC X(20) OCCURS 18.
       01 TAUDIS-DIR.
         COPY  T800      REPLACING 'X' BY T-D.
         COPY  T84D      REPLACING 'X' BY T-D.
       01 TAUDIS-COM.
         COPY  T800      REPLACING 'X' BY T-C.
         COPY  T84C      REPLACING 'X' BY T-C.
       01 TAUDIS-IFP-TRESO.
         COPY  T800      REPLACING 'X' BY T-R.
         COPY  T84R      REPLACING 'X' BY T-R.
       PROCEDURE DIVISION.
           OPEN OUTPUT TAUDIS
           CLOSE TAUDIS
           OPEN I-O TAUDIS
           OPEN INPUT RATES
           IF TAUDIS-FS NOT = '00' OR RATES-FS NOT = '00'
              DISPLAY 'LOADTAU: OPEN TAUDIS ' TAUDIS-FS
                      ' RATES ' RATES-FS
              MOVE 12 TO RETURN-CODE
              STOP RUN
           END-IF
           PERFORM UNTIL EOF-SW = 'Y'
              READ RATES
                 AT END MOVE 'Y' TO EOF-SW
                 NOT AT END PERFORM ONE-COMMUNE
              END-READ
           END-PERFORM
           CLOSE TAUDIS RATES
           DISPLAY 'LOADTAU: DIRECTIONS ' NDIR ' COMMUNES ' NCOM
                   ' IFP ' NIFP ' WRITE ERRORS ' NERR
           IF NERR > 0
              MOVE 8 TO RETURN-CODE
           END-IF
           GOBACK.
       ONE-COMMUNE.
           MOVE SPACES TO TOK-TAB
           UNSTRING RATE-REC DELIMITED BY ';' INTO
              TOK(1) TOK(2) TOK(3) TOK(4) TOK(5) TOK(6) TOK(7) TOK(8)
              TOK(9) TOK(10) TOK(11) TOK(12) TOK(13) TOK(14) TOK(15)
              TOK(16) TOK(17) TOK(18)
           END-UNSTRING
      * DIRECTION RECORD, ONCE PER DIRECTION (A REPEAT IS REFUSED)
           INITIALIZE TAUDIS-DIR
           MOVE TOK(1)(1:3)  TO T-D-DEPDIR
           MOVE LOW-VALUE    TO T-D-CCOCOM T-D-CCOIFP T-D-CCPPER
           COMPUTE T-D-PTBDEP = FUNCTION NUMVAL(TOK(5))
           COMPUTE T-D-PTBTAS = FUNCTION NUMVAL(TOK(6))
           MOVE TAUDIS-DIR TO TAUDIS-DATA
           WRITE TAUDIS-DATA
              INVALID KEY CONTINUE
              NOT INVALID KEY ADD 1 TO NDIR
           END-WRITE
      * COMMUNE RECORD
           INITIALIZE TAUDIS-COM
           MOVE TOK(1)(1:3)  TO T-C-DEPDIR
           MOVE TOK(2)(1:3)  TO T-C-CCOCOM
           MOVE LOW-VALUE    TO T-C-CCOIFP T-C-CCPPER
           MOVE 'V'          TO T-C-GCOVEF
           MOVE TAUDIS-COM TO TAUDIS-DATA
           WRITE TAUDIS-DATA
              INVALID KEY ADD 1 TO NERR
              NOT INVALID KEY ADD 1 TO NCOM
           END-WRITE
      * IFP RECORD: THE BUILT-PROPERTY RATES OF THE COMMUNE
           INITIALIZE TAUDIS-IFP-TRESO
           MOVE TOK(1)(1:3)  TO T-R-DEPDIR
           MOVE TOK(2)(1:3)  TO T-R-CCOCOM
           MOVE TOK(3)(1:3)  TO T-R-CCOIFP
           MOVE TOK(4)(1:3)  TO T-R-CCPPER
           COMPUTE T-R-PTBCOM    = FUNCTION NUMVAL(TOK(7))
           COMPUTE T-R-PTBSYN    = FUNCTION NUMVAL(TOK(8))
           COMPUTE T-R-PTBCU     = FUNCTION NUMVAL(TOK(9))
           COMPUTE T-R-PTBTSN(1) = FUNCTION NUMVAL(TOK(10))
           COMPUTE T-R-PTBTSN(2) = FUNCTION NUMVAL(TOK(11))
           COMPUTE T-R-PTBGEM    = FUNCTION NUMVAL(TOK(12))
           COMPUTE T-R-PBBOMP    = FUNCTION NUMVAL(TOK(13))
           COMPUTE T-R-PBBOMA    = FUNCTION NUMVAL(TOK(14))
           COMPUTE T-R-PBBOMB    = FUNCTION NUMVAL(TOK(15))
           COMPUTE T-R-PBBOMC    = FUNCTION NUMVAL(TOK(16))
           COMPUTE T-R-PBBOMD    = FUNCTION NUMVAL(TOK(17))
           COMPUTE T-R-PBBOME    = FUNCTION NUMVAL(TOK(18))
           MOVE TAUDIS-IFP-TRESO TO TAUDIS-DATA
           WRITE TAUDIS-DATA
              INVALID KEY ADD 1 TO NERR
              NOT INVALID KEY ADD 1 TO NIFP
           END-WRITE.
