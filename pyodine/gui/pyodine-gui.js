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

  function updatePlot(plot_div, times, values, crop_time=1000) {

    let div = $(plot_div);
    const display_time = document.getElementById('display_time').value;
    const newPoint = {x: new Date(times[0] * 1000), y: parseFloat(values[0])};

    if (typeof(div.data('chart')) !== 'undefined') {  // Plot exists, update it.
      const now = $('#use_server_clock:checked').length ? newPoint.x : new Date();
      const chart = div.data('chart');
      chart.options.data[0].dataPoints.push(newPoint);
      const age = (newPoint.x - chart.options.data[0].dataPoints[0].x) / 1000.0;
      if (age > crop_time) {
        chart.options.data[0].dataPoints = chart.options.data[0].dataPoints.slice(11);
      }
      // if (age > display_time) {
        chart.options.axisX.minimum = new Date(now - display_time * 1000);
      // }
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Create new plot.
      const chart = new CanvasJS.Chart(plot_div, { 
        title: {
          text: plot_div.dataset['title'],
        },
        data: [{
          type: 'stepLine',
          axisYType: 'secondary',
          dataPoints: [newPoint],
          markerType: 'none',
        }],
        interactivityEnabled: true,
        animationEnabled: true,
        axisX: {
          labelAngle: 30,
          gridThickness: 1,
        },
        axisY2: {
          title: div.data('ylabel'),
          gridThickness: 1,
          includeZero: false,
        },
      });
      chart.render();	
      $(plot_div).data('chart', chart);
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
  $('div.slider').each(function() {
    const container = $(this);
    const handle = $('.ui-slider-handle', container);
    container.slider({
      min: 0,
      max: 360,
      step: 0.1,
      create: function() {
        handle.text(container.slider("value") + " °");
      },
      slide: function(event, ui) {
        handle.text(ui.value + " °");
      }
    });
  });

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
