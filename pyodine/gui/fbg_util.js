/* eslint-env es6, browser */

// This is a class solely for the sake of namespacing. It is not stateful. As
// soon as browsers support ES7 modules, we can drop this crutch.
class FbgUtil {  // eslint-disable-line no-unused-vars
  // Convert binary data (uint16) encoded as base64 string into a typed array.
  static base64toUint16(base64String) {
    const buffer = this.base64toArrayBuffer(base64String);
    return new Uint16Array(buffer);
  }

  // There are multiple ways to convert a base64-encoded string into an
  // ArrayBuffer. Most of them are documented here:
  // http://eugeneware.com/software-development/converting-base64-datauri-strings-into-blobs-or-typed-array
  // For this library, I'll stick with the easiest-to-understand and very fast
  // "Uint8Array" way of using a typed array as transition.
  // It's a shame that there's no native way to do this.
  static base64toArrayBuffer(base64String) {
    const binaryString = atob(base64String);
    const nBytes = binaryString.length;
    const arr = new Uint8Array(nBytes);  // Contained data is not const.
    for (let i = 0; i < nBytes; i += 1) {
      arr[i] = binaryString.charCodeAt(i);
    }
    return arr.buffer;
  }

  // Transform a 1d `Array` to a 2d `Array` with `columns` columns:
  // >>> reshapeArray([1, 2, 3, 4, 5, 6], 3)  === [[1, 2, 3], [4, 5, 6]];
  static reshapeArray(arr, columns) {
    // This is some sick-as hyper-condensed form I "borrowed" from the
    // internets.
    return arr.reduce(
      (rows, key, index) =>
        // Note the unnecessary but cool `return <True> && actualReturn` form.
        (index % columns === 0 ? rows.push([key]) : rows[rows.length - 1].push(key)) && rows,
      [],
    );
  }
}
