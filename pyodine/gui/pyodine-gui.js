'use strict';

jQuery(function(){

  const DOM_SCOPE = document.body;
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function createDummyStreamer(plotElm) {
    var temp = {
      y: [0],
      mode: 'lines'
    };
    var data = [temp];
    var layout = {title: "Dummy Data!"};
    var plt = document.getElementById('sup1_ld_temp');
    var display_range = 100;

    Plotly.newPlot(plt, data, layout);
    while (true) {
      Plotly.extendTraces(plt, {y: [[Math.random()]]}, [0], display_range);
      var count = plt.data[0].y.length;
      await sleep(50);
    }
  }

  function updatePlot(plot_div, times, values, display_count=150) {
    if (typeof(plot_div.data) == 'object') {  // Plot exists, update it.
      Plotly.extendTraces(plot_div, {x: [times], y: [values]}, [0], display_count);
    } else {  // Create new plot.
      var layout = {
        title: plot_div.dataset['title'],
        xaxis: {
          title: "Time of Measurement in s"
        },
        yaxis: {
          title: plot_div.dataset['ylabel']
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

  function updateAllPlots(new_values_obj) {

    // Gather available plot areas.
    let available_plots = {};
    $('div.plot',DOM_SCOPE).each(function(){
      available_plots[this.id] = this;
    });

    // Update them.
    for (const id in available_plots) {
      if (id in new_values_obj) {
        const xvals = new_values_obj[id][0];
        const yvals = new_values_obj[id][1];
        updatePlot(available_plots[id], xvals, yvals);
      } else {
        console.log(`Received message didn't include data to update plot "${id}"`)
      }
    }
  }

  // Setup layout using jQuery UI.
  $('div.tabs').tabs();

  var messageHandler = function(event) {
    var message = JSON.parse(event.data);
    switch (message.type) {
      case 'readings':
        updateAllPlots(message.data);
        break;
      default:
        console.warn('Unknown message type "' + message.type + '".');
    }
  };

  var ws;
  $('#connect_btn').on('click', function() {
    var host = $('#host').val();
    var ws_port = $('#ws_port').val();
    ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
    ws.onmessage = messageHandler;
  });
});
