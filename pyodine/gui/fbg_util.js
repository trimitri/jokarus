/* eslint-env es6, browser */

// This is a class solely for the sake of namespacing. It is not stateful. As
// soon as browsers support ES7 modules, we can drop this crutch.
class FbgUtil {  // eslint-disable-line no-unused-vars
  static base64toUint16(base64String) {
    const binaryString = atob(base64String);
    const nBytes = binaryString.length;
    const bytes = new Uint16Array(nBytes);  // Contained data is not const.
    for (let i = 0; i < nBytes; i += 1) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
  }
}
