'use strict';

jQuery(function(){

  async function foo() {
    // Setup layout using jQuery UI.
    $('#tabs').tabs();

    var messageHandler = function(event) {
      document.body.appendChild(document.createTextNode(event.data)); 
    };

    var ws;
    $('#connect_btn').on('click', function() {
      var host = $('#host').val();
      var ws_port = $('#ws_port').val();
      ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
      ws.onmessage = messageHandler;
    });

    var plt_id = 'sup1_ld_temp'
    var temp = {
      y: [10, 4, 12, 3, 4, 5, 16, 17],
      mode: 'lines'
    };
    var data = [temp];
    var layout = {
      title: 'SUP1 Laser Diode Temp.'
    };

    function sleep(ms) {
      return new Promise(resolve => setTimeout(resolve, ms));
    }

    Plotly.newPlot(plt_id, data, layout);
    for (var i = 0; i<100; i++) {
      Plotly.extendTraces(plt_id, {y: [[20]]}, [0]);
      await sleep(1000);
    }
  }

  foo();
});
