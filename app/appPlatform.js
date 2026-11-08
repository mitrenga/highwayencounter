const { ZXPlatform } = await import('./svision/js/platform/canvas2D/zx/zxPlatform.js?ver='+window.srcVersion);
// begin code

/**
 * Highway Encounter runs on the ZX Spectrum platform of svision: a 256x192
 * desktop with a border, integer scaling and the Spectrum palette — the same
 * machine the original ran on (ZADANI chap. 1).
 */
export function appPlatform() {
  return new ZXPlatform();
} // appPlatform
