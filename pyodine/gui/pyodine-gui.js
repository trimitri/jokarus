'use strict';

jQuery(function(){

  // Setup layout using jQuery UI.
  $('#tabs').tabs();

  var messageHandler = function(event) {
   document.body.appendChild(document.createTextNode(event.data)); 
  };

  // Connect to server.
  var ws;
  $('#connect_btn').on('click', function() {
    var host = $('#host').val();
    var ws_port = $('#ws_port').val();
    ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
    ws.onmessage = messageHandler;
  });
});
