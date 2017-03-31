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
- :doc:`pyodine.transport`: Tools für externe Kommunikation, Protokolle
- :doc:`pyodine.test`: Test-Module, die automatisiert alle wesentlichen
  Funktionen aller anderen Module testen ("test based development")

Begründungen zu einzelnen Designideen
-------------------------------------

Warum Server und Client so strikt trennen?
    So kann der Server möglichst schlank und somit weniger fehleranfällig
    gehalten werden. Wenn es Probleme mit der Oberfläche gibt, kann der Server
    einfach weiterlaufen. Die Benutzeroberfläche kann beliebig oft verbunden
    oder getrennt werden.

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
