// Minimal WOFF/WOFF2 reader: returns the set of mapped code points (cmap) and the
// OpenType feature tags (GSUB) of a font file. Used by check_glyphs.mjs. No dependencies:
// WOFF tables are zlib-compressed and WOFF2 is one brotli stream, both handled by node:zlib.
import { readFileSync } from 'node:fs';
import { brotliDecompressSync, inflateSync } from 'node:zlib';

const WOFF2_KNOWN_TAGS = [
  'cmap',
  'head',
  'hhea',
  'hmtx',
  'maxp',
  'name',
  'OS/2',
  'post',
  'cvt ',
  'fpgm',
  'glyf',
  'loca',
  'prep',
  'CFF ',
  'VORG',
  'EBDT',
  'EBLC',
  'gasp',
  'hdmx',
  'kern',
  'LTSH',
  'PCLT',
  'VDMX',
  'vhea',
  'vmtx',
  'BASE',
  'GDEF',
  'GPOS',
  'GSUB',
  'EBSC',
  'JSTF',
  'MATH',
  'CBDT',
  'CBLC',
  'COLR',
  'CPAL',
  'SVG ',
  'sbix',
  'acnt',
  'avar',
  'bdat',
  'bloc',
  'bsln',
  'cvar',
  'fdsc',
  'feat',
  'fmtx',
  'fvar',
  'gvar',
  'hsty',
  'just',
  'lcar',
  'mort',
  'morx',
  'opbd',
  'prop',
  'trak',
  'Zapf',
  'Silf',
  'Glat',
  'Gloc',
  'Feat',
  'Sill',
];

function readBase128(buf, pos) {
  let value = 0;
  for (let i = 0; i < 5; i++) {
    const byte = buf[pos.at++];
    value = value * 128 + (byte & 0x7f);
    if ((byte & 0x80) === 0) return value;
  }
  throw new Error('bad UIntBase128');
}

function woff2Tables(buf) {
  const numTables = buf.readUInt16BE(12);
  const pos = { at: 48 };
  const entries = [];
  for (let i = 0; i < numTables; i++) {
    const flags = buf[pos.at++];
    let tag;
    if ((flags & 0x3f) === 0x3f) {
      tag = buf.toString('latin1', pos.at, pos.at + 4);
      pos.at += 4;
    } else {
      tag = WOFF2_KNOWN_TAGS[flags & 0x3f];
    }
    const version = flags >> 6;
    const origLength = readBase128(buf, pos);
    const transformed = tag === 'glyf' || tag === 'loca' ? version === 0 : version !== 0;
    const length = transformed ? readBase128(buf, pos) : origLength;
    entries.push({ tag, length });
  }
  const totalCompressed = buf.readUInt32BE(20);
  const data = brotliDecompressSync(buf.subarray(pos.at, pos.at + totalCompressed));
  const tables = {};
  let offset = 0;
  for (const { tag, length } of entries) {
    tables[tag] = data.subarray(offset, offset + length);
    offset += length;
  }
  return tables;
}

function woffTables(buf) {
  const numTables = buf.readUInt16BE(12);
  const tables = {};
  for (let i = 0; i < numTables; i++) {
    const at = 44 + i * 20;
    const tag = buf.toString('latin1', at, at + 4);
    const offset = buf.readUInt32BE(at + 4);
    const compLength = buf.readUInt32BE(at + 8);
    const origLength = buf.readUInt32BE(at + 12);
    const raw = buf.subarray(offset, offset + compLength);
    tables[tag] = compLength < origLength ? inflateSync(raw) : raw;
  }
  return tables;
}

function cmapCodePoints(cmap) {
  const points = new Set();
  const count = cmap.readUInt16BE(2);
  for (let i = 0; i < count; i++) {
    const sub = cmap.readUInt32BE(4 + i * 8 + 4);
    const format = cmap.readUInt16BE(sub);
    if (format === 4) {
      const segX2 = cmap.readUInt16BE(sub + 6);
      const ends = sub + 14;
      const starts = ends + segX2 + 2;
      const deltas = starts + segX2;
      const rangeOffsets = deltas + segX2;
      for (let s = 0; s < segX2 / 2; s++) {
        const end = cmap.readUInt16BE(ends + s * 2);
        const start = cmap.readUInt16BE(starts + s * 2);
        const delta = cmap.readInt16BE(deltas + s * 2);
        const ro = cmap.readUInt16BE(rangeOffsets + s * 2);
        for (let c = start; c <= end && c !== 0xffff; c++) {
          let glyph;
          if (ro === 0) glyph = (c + delta) & 0xffff;
          else {
            const at = rangeOffsets + s * 2 + ro + (c - start) * 2;
            glyph = cmap.readUInt16BE(at);
            if (glyph !== 0) glyph = (glyph + delta) & 0xffff;
          }
          if (glyph !== 0) points.add(c);
        }
      }
    } else if (format === 12) {
      const groups = cmap.readUInt32BE(sub + 12);
      for (let g = 0; g < groups; g++) {
        const at = sub + 16 + g * 12;
        const start = cmap.readUInt32BE(at);
        const end = cmap.readUInt32BE(at + 4);
        const startGlyph = cmap.readUInt32BE(at + 8);
        for (let c = start; c <= end; c++) if (startGlyph + (c - start) !== 0) points.add(c);
      }
    }
  }
  return points;
}

function gsubFeatures(gsub) {
  const tags = new Set();
  if (!gsub) return tags;
  const list = gsub.readUInt16BE(6);
  const count = gsub.readUInt16BE(list);
  for (let i = 0; i < count; i++) {
    tags.add(gsub.toString('latin1', list + 2 + i * 6, list + 6 + i * 6));
  }
  return tags;
}

/** Read a .woff or .woff2 file and return { codePoints, features }. */
export function fontInfo(path) {
  const buf = readFileSync(path);
  const signature = buf.toString('latin1', 0, 4);
  const tables =
    signature === 'wOF2' ? woff2Tables(buf) : signature === 'wOFF' ? woffTables(buf) : null;
  if (!tables) throw new Error(`${path}: not a WOFF/WOFF2 file`);
  return { codePoints: cmapCodePoints(tables.cmap), features: gsubFeatures(tables.GSUB) };
}
