      *HARNESS: our code (MIT), not part of the DGFiP sources.
      * Stands in for the calling system of the 2018 built-property
      * calculator. It opens the rate file TAUDIS (declared EXTERNAL,
      * shared with the unmodified EFITAUX2), reads each 600-byte bill
      * (copybook XCOMBAT) from DD BILLS, calls the unmodified CTXTA3B
      * with CRM = 99 (rates read through EFITAUX2), and writes the
      * 600-byte return area (copybook XRETB) to DD RETOURS. The two
      * return codes CRM and RCM go into the last 4 bytes of the
      * record, which are FILLER in XRETB.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TFBATCH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAUDIS ASSIGN TO TAUDIS
                  ORGANIZATION INDEXED
                  ACCESS MODE DYNAMIC
                  RECORD KEY TAUDIS-CLE
                  FILE STATUS TAUDIS-FS.
           SELECT BILLS ASSIGN TO BILLS
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS BILLS-FS.
           SELECT RETOURS ASSIGN TO RETOURS
                  ORGANIZATION SEQUENTIAL
                  FILE STATUS RETOURS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TAUDIS EXTERNAL
           RECORD CONTAINS 3000 CHARACTERS.
       01  TAUDIS-DATA.
           02 TAUDIS-CLE.
              05 T-DIR               PIC X(3).
              05 T-COM               PIC X(3).
              05 T-CCOIFP            PIC X(3).
              05 T-CCPPER            PIC X(3).
           02 TAUDIS-SUITE           PIC X(2988).
       FD  BILLS
           RECORD CONTAINS 600 CHARACTERS.
       01  BILL-REC                  PIC X(600).
       FD  RETOURS
           RECORD CONTAINS 600 CHARACTERS.
       01  RETOUR-REC                PIC X(600).
       WORKING-STORAGE SECTION.
       01  TAUDIS-FS                 PIC XX EXTERNAL.
       01  BILLS-FS                  PIC XX.
       01  RETOURS-FS                PIC XX.
       01  EOF-SW                    PIC X VALUE 'N'.
       01  NREC                      PIC 9(7) VALUE 0.
       01  NERR                      PIC 9(7) VALUE 0.
       01  ENTREE                    PIC X(600).
       01  SORTIE                    PIC X(600).
       01  CRM                       PIC 9(2).
       01  RCM                       PIC 9(2).
       PROCEDURE DIVISION.
           OPEN INPUT TAUDIS
           IF TAUDIS-FS NOT = '00'
              DISPLAY 'TFBATCH: OPEN TAUDIS FILE STATUS ' TAUDIS-FS
              MOVE 12 TO RETURN-CODE
              STOP RUN
           END-IF
           OPEN INPUT BILLS
           OPEN OUTPUT RETOURS
           IF BILLS-FS NOT = '00' OR RETOURS-FS NOT = '00'
              DISPLAY 'TFBATCH: OPEN BILLS ' BILLS-FS
                      ' RETOURS ' RETOURS-FS
              MOVE 12 TO RETURN-CODE
              STOP RUN
           END-IF
           PERFORM UNTIL EOF-SW = 'Y'
              READ BILLS INTO ENTREE
                 AT END MOVE 'Y' TO EOF-SW
                 NOT AT END PERFORM ONE-BILL
              END-READ
           END-PERFORM
           CLOSE TAUDIS BILLS RETOURS
           DISPLAY 'TFBATCH: BILLS ' NREC
                   ' WITH A NON-ZERO RETURN CODE ' NERR
           GOBACK.
       ONE-BILL.
           ADD 1 TO NREC
           MOVE SPACES TO SORTIE
           MOVE 99 TO CRM
           MOVE 0 TO RCM
           CALL 'CTXTA3B' USING ENTREE SORTIE CRM RCM
           IF CRM NOT = 0
              ADD 1 TO NERR
           END-IF
           MOVE SORTIE TO RETOUR-REC
           MOVE CRM TO RETOUR-REC(597:2)
           MOVE RCM TO RETOUR-REC(599:2)
           WRITE RETOUR-REC.
