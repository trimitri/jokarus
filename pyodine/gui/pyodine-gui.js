'use strict';

jQuery(function(){

  async function createDummyStreamer(plotElm, title) {
    var temp = {
      y: [0],
      mode: 'lines'
    };
    var data = [temp];
    var layout = {title: title};
    var plt = document.getElementById('sup1_ld_temp');
    var display_range = 100;

    Plotly.newPlot(plt, data, layout);
    while (true) {
      Plotly.extendTraces(plt, {y: [[Math.random()]]}, [0], display_range);
      var count = plt.data[0].y.length;
      await sleep(50);
    }
  }

  // Setup layout using jQuery UI.
  $('#tabs').tabs();

  var messageHandler = function(event) {
    document.body.appendChild(document.createTextNode(event.data)); 
  };

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  createDummyStreamer(document.getElementById('sup1_ld_temp'), "SUP1 Laser Diode Temp.");
  // createDummyStreamer(document.getElementById('sup1_ld_current'), "SUP1 Laser Diode Current");
  // createDummyStreamer(document.getElementById('sup1_tec_current'), "SUP1 Peltier Current");

  var ws;
  $('#connect_btn').on('click', function() {
    var host = $('#host').val();
    var ws_port = $('#ws_port').val();
    ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
    ws.onmessage = messageHandler;
  });
});
