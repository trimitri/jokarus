Unit A
======
Card        Function                 Notes
------------------------------------------
OSC1: 0004  MO, TEC Kovar, NTC MiOB  CAN works, low power
OSC2: 0005  TEC VHBG, no LD          CAN works, DIY cooling construction, low power
OSC3: 0006  not used                 CAN works, high power
OSC4: 0007  SHG A, no LD             CAN works, sense wires, low power
PII1: 4     Freq. lock               CAN works, but is actually 2:...
PII2: 3     not used                 CAN broken: doesn't send anything
ADC:  031   not used                 Spule am Rand der Platine gebrochen
MUC:  "A"   not used                 vermutlich durch Kurzschluss beschädigt

Unit B
======
Card           Function          Notes
--------------------------------------
OSC1: 0031216  not used          CAN works, high power
OSC2: 0021216  not used          CAN works, high power
OSC3: 0041216  PA, SHG B         CAN works, NTC fixed to board, high power
OSC4: 0011216  not used          CAN works, current driver broken, high power
PII1:                            still in Munich
PII2: 2        not used          sends at crazy rate, Kapton isolating err. in
ADC:  032      not used          physisch i.O.
MUC:  ?        used              works
