'use strict';

jQuery(function(){

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

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

  function updatePlot(plot_div, times, values, display_count=40) {

    if (typeof(plot_div.data) == 'object') {  // Plot exists, update it.
      Plotly.extendTraces(plot_div, {x: [times], y: [values]}, [0], display_count);
    } else {  // Create new plot.
      var layout = {
        title: "Some Voltage",
        xaxis: {
          type: 'linear',
          title: 'time of measurement'
        },
      };
      var data = [{
        mode: 'lines',
        x: times,
        y: values
      }];
      Plotly.newPlot(plot_div, data, layout);
    }
  }

  // Setup layout using jQuery UI.
  $('#tabs').tabs();

  var messageHandler = function(event) {
    var data = JSON.parse(event.data);
    updatePlot($("#some_voltage")[0], [data.some_voltage[1]], [data.some_voltage[0]])
  };

  var ws;
  $('#connect_btn').on('click', function() {
    var host = $('#host').val();
    var ws_port = $('#ws_port').val();
    ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
    ws.onmessage = messageHandler;
  });
});
