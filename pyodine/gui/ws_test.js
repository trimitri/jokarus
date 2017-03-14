'use strict';

jQuery(function(){

  $('#tabs').tabs();

  var ws = new WebSocket("ws://localhost:12345/");
});
