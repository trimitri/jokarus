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

  function updatePlot(plot_div, points, crop_time=1000) {

    let div = $(plot_div);
    const display_time = document.getElementById('display_time').value;

    // For now, we are only using the first point of the received dataset, even
    // if it contains more. TODO allow adding more points at once.
    const newPoint = {x: new Date(points[0][0] * 1000),
                      y: parseFloat(points[0][1])};

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
        updatePlot(available_plots[id], new_values_obj[id]);
      } else {
        console.log(`Received message didn't include data to update plot "${id}"`)
      }
    }
  }

  function updateTexusFlags(new_values_obj) {
    for (const key in new_values_obj) {
      updateFlag(key, new_values_obj[key]);
    }
  }

  function updateFlag(entity_id, new_value) {
    const container = $(`tr[data-flag=${entity_id}]`);
    const indicators = $('td.indicator', container);
    if (new_value !== container.data('value')) {
      container.data('value', new_value);
      $('td.changed', container).html((new Date()).toLocaleTimeString())
    }
    indicators.html(new_value ? "On" : "Off");
    indicators.css('backgroundColor', new_value ? 'green' : 'red');
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  function sendFlag(entityId, value) {
    const message = createMessage({
      method: 'setflag',
      args: [entityId, value]
    });
    sendMessage(message);
  }

  function sendMessage(message) {
    ws.send(message)
  }

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return JSON.stringify(wrapper) + '\n\n\n';
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
      case 'texus':
        updateTexusFlags(message.data);
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


  $('#send_btn').on('click', function() {
    const message = $('#send_data').val();
    console.log("Sending: " + message);
    sendMessage(message);
  });

  $('tr[data-flag]').each(function(){
    const container = $(this);
    $('.switch', this).on('click', function() {
      sendFlag(container.data('flag'), $(this).hasClass('on'));
    });
  });

  // TOOLS

  $('[data-safety-switch]').each(function(){
    const sswitch = $(this);
    const controls = $(sswitch.data('safetySwitch'));
    controls.prop('disabled', true);
    sswitch.on('change', function() {
      controls.prop('disabled', this.checked ? false : true);
    });
    controls.on('click', function() {
      sswitch.prop('checked', false);
      sswitch.trigger('change');
    });
  });
});
