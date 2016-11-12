"""This is the root package of Pyodine.

It doesn't do anything except marking this folder to be a python project.

Due to laziness, here is some general explanation of the project structure in
German:

Ein kurzer Überblick über die geplante Projektstruktur
------------------------------------------------------

- "Pyodine": Name des Python-Pakets welches alle anderen Softwarekomponenten
  integriert
- :doc:`pyodine.drivers`: Gerätetreiber.
- :doc:`pyodine.gui`: Grafische Oberfläche (evtl. einfach HTML/JavaScript,
  siehe unten)
- :doc:`pyodine.controller`: Eigentliche Steuerung des Programmflusses,
  Finden-und-Locken-Mechanismus etc.
- :doc:`pyodine.comm`: Tools für die Kommunikation zwischen verschiedenen
  Programmteilen (z.B. Pyodine-Server in der Rakete und GUI am Boden)
- :doc:`pyodine.test`: Test-Module, die automatisiert alle wesentlichen
  Funktionen aller anderen Module testen ("test based development")

Von der Sache her stelle ich mir das so vor: Am Experiment (also auf dem
Pokini) läuft das Hauptprogramm. Es besteht aus mehreren Subprozessen (oder
Threads, noch nicht entschieden), die für die einzelnen Subsysteme des Aufbaus
verantwortlich sind. Dieses Hauptprogromm ("Pyodine Server") hat keine
grafische Oberfläche.  Es stellt sein Interface stattdessen über einen
RPC-Service (vermutlich XML-RPC, evtl JSON-RPC) zur Verfügung.  Die grafische
Oberfläche wird vermutlich einfach eine HTML-Datei mit div. kleinen JS-Skripten
sein (um Schieber, Knöpfe, Signalplots etc. anzuzeigen), die als RPC-Client mit
dem Server kommuniziert.

Begründungen zu einzelnen Designideen
-------------------------------------

Warum Server und Client so strikt trennen?
    So kann der Server möglichst schlank und somit weniger fehleranfällig
    gehalten werden. Wenn es Probleme mit der Oberfläche gibt, kann der Server
    einfach weiterlaufen. Die Benutzeroberfläche kann beliebig oft verbunden
    oder getrennt werden.

Warum RPC?
    Ich habe mir einige Protokolle angeschaut und alle anderen wären vermutlich
    overkill.

Warum eine HTML-Oberfläche?
    HTML ist simpel und allgegenwärtig. Das hat den Vorteil, dass auf dem
    Kontrollrechner (welcher auch immer das sein mag) nichts als ein Browser
    installiert sein muss. Zudem ist denkbar, dass mehrere Clients mit dem
    Server kommunizieren, also z.B. von mehreren Stellen aus der aktuelle
    Zustand des Experiments eingesehen und ggf. beeinflusst werden kann.  Und
    man muss sich nicht mit Qt, TKinter oder anderen GUI-Bibliotheken
    auseinandersetzen.

Warum überhaupt so viele Einzelprogrämmchen?
    Damit das automatisierte Testen überschaubar bleibt, und evtl. Fehler nur
    lokale Konsequenzen haben. Und weil es schöner ist...
"""

pass  # explicitly do nothing
