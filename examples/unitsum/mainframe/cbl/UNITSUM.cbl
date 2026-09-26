      * TEST FIXTURE for Tare's self-test, not a case.
      * Reads shipped item lines sorted by item id (ITEMFILE) and writes
      * one total per id (TOTFILE, indexed by OUT-ID): the number of
      * lines, the total quantity, the total weight in kg (3 decimals)
      * and the same weight in pounds (2 decimals). The pounds COMPUTE
      * has no ROUNDED phrase, so it truncates.
      * An optional PARM (a run label) is shown on the job log.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNITSUM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ITEM-FILE ASSIGN TO ITEMFILE
                  ORGANIZATION IS SEQUENTIAL
                  FILE STATUS  IS WS-ITEM-STATUS.
           SELECT TOTAL-FILE ASSIGN TO TOTFILE
                  ORGANIZATION IS INDEXED
                  ACCESS MODE  IS SEQUENTIAL
                  RECORD KEY   IS OUT-ID
                  FILE STATUS  IS WS-TOTAL-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  ITEM-FILE.
       COPY ITEMREC.
       FD  TOTAL-FILE.
       COPY TOTALREC.
       WORKING-STORAGE SECTION.
       01  WS-ITEM-STATUS             PIC X(02).
       01  WS-TOTAL-STATUS            PIC X(02).
       01  WS-EOF                     PIC X(01) VALUE 'N'.
       01  WS-CURRENT-ID              PIC X(06) VALUE SPACES.
       01  WS-LINE-KG                 PIC 9(08)V999.
       01  WS-ITEMS-READ              PIC 9(05) VALUE 0.
       01  WS-TOTALS-WRITTEN          PIC 9(05) VALUE 0.
       01  WS-ABCODE                  PIC S9(9) BINARY.
       01  WS-TIMING                  PIC S9(9) BINARY VALUE 0.
       LINKAGE SECTION.
       01  RUN-PARM.
           05 RUN-PARM-LENGTH         PIC S9(04) COMP.
           05 RUN-PARM-TEXT           PIC X(100).
       PROCEDURE DIVISION USING RUN-PARM.
       0000-MAIN.
           IF ADDRESS OF RUN-PARM NOT = NULL
               IF RUN-PARM-LENGTH > 0
                   DISPLAY 'UNITSUM: PARM='
                           RUN-PARM-TEXT(1:RUN-PARM-LENGTH)
               END-IF
           END-IF
           OPEN INPUT ITEM-FILE
           IF WS-ITEM-STATUS NOT = '00'
               DISPLAY 'UNITSUM: OPEN ITEMFILE STATUS ' WS-ITEM-STATUS
               PERFORM 9999-ABEND
           END-IF
           OPEN OUTPUT TOTAL-FILE
           IF WS-TOTAL-STATUS NOT = '00'
               DISPLAY 'UNITSUM: OPEN TOTFILE STATUS ' WS-TOTAL-STATUS
               PERFORM 9999-ABEND
           END-IF
           PERFORM 1000-READ-ITEM
           PERFORM UNTIL WS-EOF = 'Y'
               IF ITEM-ID NOT = WS-CURRENT-ID
                   IF WS-CURRENT-ID NOT = SPACES
                       PERFORM 2000-WRITE-TOTAL
                   END-IF
                   PERFORM 1500-START-TOTAL
               END-IF
               COMPUTE WS-LINE-KG = ITEM-QTY * ITEM-UNIT-KG
               ADD WS-LINE-KG TO OUT-TOTAL-KG
               ADD ITEM-QTY TO OUT-QTY
               ADD 1 TO OUT-COUNT
               PERFORM 1000-READ-ITEM
           END-PERFORM
           IF WS-CURRENT-ID NOT = SPACES
               PERFORM 2000-WRITE-TOTAL
           END-IF
           CLOSE ITEM-FILE TOTAL-FILE
           DISPLAY 'UNITSUM: ITEMS READ ' WS-ITEMS-READ
                   ' TOTALS WRITTEN ' WS-TOTALS-WRITTEN
           GOBACK.

       1000-READ-ITEM.
           READ ITEM-FILE
               AT END
                   MOVE 'Y' TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-ITEMS-READ
           END-READ
           IF WS-ITEM-STATUS NOT = '00' AND NOT = '10'
               DISPLAY 'UNITSUM: READ ITEMFILE STATUS ' WS-ITEM-STATUS
               PERFORM 9999-ABEND
           END-IF.

       1500-START-TOTAL.
           MOVE ITEM-ID TO WS-CURRENT-ID
           MOVE SPACES TO TOTAL-RECORD
           MOVE ITEM-ID TO OUT-ID
           MOVE 0 TO OUT-COUNT OUT-QTY OUT-TOTAL-KG OUT-TOTAL-LB.

       2000-WRITE-TOTAL.
           COMPUTE OUT-TOTAL-LB = OUT-TOTAL-KG * 2.20462
           WRITE TOTAL-RECORD
           IF WS-TOTAL-STATUS NOT = '00'
               DISPLAY 'UNITSUM: WRITE TOTFILE STATUS ' WS-TOTAL-STATUS
               PERFORM 9999-ABEND
           END-IF
           ADD 1 TO WS-TOTALS-WRITTEN.

       9999-ABEND.
           MOVE 999 TO WS-ABCODE
           CALL 'CEE3ABD' USING WS-ABCODE WS-TIMING.
