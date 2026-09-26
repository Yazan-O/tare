      * TEST FIXTURE: one total per item id, 40 bytes, keyed by OUT-ID.
       01  TOTAL-RECORD.
           05 OUT-ID                  PIC X(06).
           05 OUT-COUNT               PIC 9(03).
           05 OUT-QTY                 PIC 9(07).
           05 OUT-TOTAL-KG            PIC 9(08)V999.
           05 OUT-TOTAL-LB            PIC S9(08)V99.
           05 FILLER                  PIC X(03).
