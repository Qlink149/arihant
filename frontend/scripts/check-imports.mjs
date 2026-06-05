import { createServer } from 'vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const server = await createServer({
  configFile: path.resolve(__dirname, '../vite.config.mjs'),
});

const modules = [
  '../src/index.jsx',
  '../src/App.js',
  '../src/pages/DashboardPage.js',
  '../src/pages/MyDashboardPage.js',
  '../src/components/leads/LeadDataTable.jsx',
];

for (const mod of modules) {
  try {
    await server.ssrLoadModule(mod);
    console.log('OK', mod);
  } catch (err) {
    console.error('FAIL', mod, err.message);
    console.error(err.stack);
  }
}

await server.close();
