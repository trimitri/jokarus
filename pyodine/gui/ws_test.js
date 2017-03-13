'use strict';

function log(text) {
  document.body.appendChild(document.createTextNode(text + '\n'));
}

var ws = new WebSocket("ws://localhost:12345/");
ws.onmessage = function (event) {
  log(event.data);
};
