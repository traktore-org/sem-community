import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default {
  input: join(__dirname, 'src/sem-cards.js'),
  output: {
    file: join(__dirname, 'dist/sem-cards.js'),
    format: 'es',
    sourcemap: false,
  },
  plugins: [
    resolve(),
    terser({ format: { comments: false } }),
  ],
};
