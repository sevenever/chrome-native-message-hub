!function (global) {
    var hub_name = 'com.sevenever.chrome_native_message_hub';
    var native_message_port = chrome.runtime.connectNative(hub_name);
    native_message_port.onMessage.addListener(function(msg) {
        if (ports[msg.extensionId] && ports[msg.extensionId][msg.hostId]) {
            ports[msg.extensionId][msg.hostId].postMessage(
                {
                    type: 'message',
                    message: msg.message
                }
            );
        }
    });

    var ports = {}; // two layers lookup table of extensionId -> hostId -> port
    chrome.runtime.onConnectExternal.addListener(function (port) {
        var extensionId = port.sender.id;
        var hostId;
        if (!ports[extensionId]) {
            ports[extensionId] = {};
        }
        port.onMessage.addListener(function (msg) {
            switch(msg.type) {
                case 'connect': {
                    if (!msg.hostId) {
                        port.postMessage(
                            {
                                type: 'response',
                                response: {
                                    successful: false,
                                    reason: 'no hostId in connect request'
                                }
                            }
                        );
                    } else {
                        hostId = msg.hostId;
                        ports[extensionId][hostId] = port;
                    }
                    break;
                }
                case 'message': {
                    if (!hostId) {
                        port.postMessage(
                            {
                                type: 'response',
                                response: {
                                    successful: false,
                                    reason: 'use connect first'
                                }
                            }
                        );
                    } else if (!msg.message) {
                        port.postMessage(
                            {
                                type: 'response',
                                response: {
                                    successful: false,
                                    reason: 'no message field in messsage'
                                }
                            }
                        );
                    } else {
                        native_message_port.postMessage({
                            extensionId: extensionId,
                            hostId: hostId,
                            message: msg.message
                        });
                    }
                    break;
                }
                default:{
                    port.postMessage(
                        {
                            type: 'response',
                            response: {
                                successful: false,
                                reason: 'unsupported type ' + msg.type
                            }
                        }
                    );
                }
            }
        });
        port.onDisconnect.addListener(function () {
            if (hostId) {
                delete ports[extensionId][hostId];
            }
            if (Object.getOwnPropertyNames(ports[extensionId]).length == 0) {
                delete ports[extensionId];
            }
        });
    })
}(this);
