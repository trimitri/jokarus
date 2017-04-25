/* eslint-env es6, browser, jquery */
/* eslint no-alert: "off" */
/* eslint no-lone-blocks: "off" */
/* global CanvasJS */
/* global Plotter */

// Require jQuery. Don't use global scope. (IIFE)
(function jqueryWrapper($) {
  'use strict';

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return `${JSON.stringify(wrapper)}\n\n\n`;
  }

  function callRemoteMethod(socket, methodName, args) {
    const msg = createMessage({
      method: methodName,
      args,
    });
    socket.send(msg);
  }

  function updateIndicator(elm, isOn) {
    const onText = elm.data('textTrue') || "ON";
    const offText = elm.data('textFalse') || "OFF";
    elm.html(isOn ? onText : offText);
    elm.css('backgroundColor', isOn ? 'green' : 'red');
  }

  function updateFlag(entityId, newValue) {
    const container = $(`tr[data-flag=${entityId}]`);
    if (newValue !== container.data('value')) {
      container.data('value', newValue);
      $('td.changed', container).html((new Date()).toLocaleTimeString());
    }
    updateIndicator($('td.indicator', container), newValue === 1);
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  function updateTexusFlags(newValuesObj) {
    Object.keys(newValuesObj).forEach((key) => {
      updateFlag(key, newValuesObj[key]);
    });
  }

  function sendFlag(socket, entityId, value) {
    callRemoteMethod(socket, 'setflag', [entityId, value]);
  }

  /**
   * Update all indicators for which there are new values in the given data.
   */
  function updateIndicators(newValuesObj) {
    // Boolean indicators
    const booleanIndicators = $(".indicator[data-qty]");
    booleanIndicators.each(function update() {
      const qty = this.dataset.qty;
      if (!(qty in newValuesObj) || newValuesObj[qty].length === 0) return;

      // Get the value ([1]) of the latest ([0]) data point.
      updateIndicator($(this), newValuesObj[qty][0][1] === 1);

      // Update "last updated" fields if any are present for qty.
      const timeOfMeasurement = new Date(newValuesObj[qty][0][0] * 1000);
      $(`.update_indicator[data-qty=${qty}]`).html(
        timeOfMeasurement.toLocaleTimeString());
    });

    // General indicators
    document.querySelectorAll('input.source[data-qty]').forEach((input) => {
      if (input.disabled) {
        // Timeline of recent values for this specific setpoint.
        // @type {Buffer}
        const setpoints = newValuesObj[input.dataset.qty];
        if (setpoints && setpoints.length) {
          input.value = setpoints[0][1];
        }
      }
    });
  }

  function messageHandler(event) {
    const message = JSON.parse(event.data);
    switch (message.type) {
      case 'readings':
        Plotter.updateAllPlots(message.data);
        $('div.osc_plot').each(function plotUpdater() {
          Plotter.updateOscPlot(this, message.data);
        });
        document.querySelectorAll('div.pii.plot[data-unit-name]').forEach(
          plotDiv => Plotter.updatePiiPlot(plotDiv, message.data));
        updateIndicators(message.data);
        break;
      case 'setup':
        updateIndicators(message.data);
        break;
      case 'texus':
        updateTexusFlags(message.data);
        break;
      default:
        console.warn(`Unknown message type "${message.type}".`);
    }
  }

  $(() => {  // Do things on page load.
    // Setup layout using jQuery UI.
    $('div.tabs').tabs();

    // Establish connection to server.
    let ws;  // Websocket connection.
    $('#connect_btn').on('click', () => {
      const host = $('#host').val();
      const wsPort = $('#ws_port').val();
      ws = new WebSocket(`ws://${host}:${wsPort}/`);
      ws.onmessage = messageHandler;
    });

    {  // Setup interactive UI elements.
      $('div.slider').each(function setupSlider() {
        const container = $(this);
        const handle = $('.ui-slider-handle', container);
        container.slider({
          min: 0,
          max: 360,
          step: 0.1,
          create() {
            handle.text(`${container.slider("value")} °`);
          },
          slide(event, ui) {
            handle.text(`${ui.value} °`);
          },
        });
      });

      // Setup send buttons in special "flag" table rows.
      $('tr[data-flag]').each(function armSendFlagBtns() {
        const container = $(this);
        $('.switch', this).on('click', function send() {
          sendFlag(ws, container.data('flag'), $(this).hasClass('on'));
        });
      });

      $('input[type=button].setter[data-qty]').each(function armSetterBtn() {
        const qty = this.dataset.qty;
        const trigger = $(this);
        const source = $(`input.source[data-qty=${qty}]`).first();
        trigger.on('click', () => {
          const value = source.val();
          if (value !== '') {
            callRemoteMethod(ws, `set_${qty}`, [value]);
          } else {
            alert("No value set. Please set a value.");
          }
        });
      });

      $('input[type=button][data-method][data-arguments]').each(
        function armMethodCallBtn() {
          const button = $(this);
          button.on('click', () => {
            const commandName = button.data('method');
            const args = button.data('arguments');
            callRemoteMethod(ws, commandName, args);
          });
        });

      // TOOLS

      $('[data-safety-switch]').each(function armSafetySwitch() {
        const sswitch = $(this);
        const controls = $(sswitch.data('safetySwitch')).filter('input');
        controls.prop('disabled', true);
        sswitch.on('change', () => {
          // Outer "this" is accessed, as we are in an arrow function.
          controls.prop('disabled', !this.checked);
        });
        controls.on('click', function armControlBtn() {
          if (this.type === 'button') {
            sswitch.prop('checked', false);
            sswitch.trigger('change');
          }
        });
      });
    }
  });
}(jQuery));
