// web-ext packs the whole extension directory. Anything dropped in here ends up
// inside the signed .xpi — a stray archive once added 9 MB to the package, and a
// version cannot be signed twice, so the mistake costs a version number.
module.exports = {
  ignoreFiles: [
    'web-ext-artifacts',
    'web-ext-config.cjs',
    '.amo-upload-uuid',
    '**/*.rar',
    '**/*.zip',
    '**/*.xpi',
    '**/*.exe',
    '**/*.md',
  ],
};
