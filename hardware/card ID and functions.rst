Unit A
======
Card        Function                 Notes
------------------------------------------
OSC1: 0004  MO, TEC Kovar, NTC MiOB  CAN works, low power
OSC2: 0005  TEC VHBG, no LD          CAN works, DIY cooling construction, low power
OSC3: 0006  not used                 CAN works, high power
OSC4: 0007  SHG B, no LD             CAN works, sense wires, low power
PII1: 4     spare f lock?            CAN works, but talks at 2: instead 1: (!)
PII2: 3     not used                 CAN broken: doesn't send anything

Unit B
======
Card           Function          Notes
--------------------------------------
OSC1: 0031216  not used          CAN works, high power
OSC2: 0021216  not used          CAN works, high power
OSC3: 0041216  PA, SHG A         CAN works, NTC fixed to board, high power
OSC4: 0011216  not used          CAN works, current driver broken, high power
PII1: 
PII2: 2        Freq. lock        CAN works, Kapton isolating err. in
