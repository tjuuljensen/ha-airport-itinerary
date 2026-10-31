const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './browser-tests',
  use: { browserName: 'chromium', headless: true },
  reporter: 'list',
});
