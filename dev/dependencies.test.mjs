import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

test('patched OpenAPI tooling preserves URL header matching with minimatch 11', async () => {
    const require = createRequire(import.meta.url);
    const generator = createRequire(require.resolve('../clients/web/node_modules/openapi-typescript/dist/index.mjs'));
    const core = createRequire(generator.resolve('@redocly/openapi-core'));
    const { readFileFromUrl } = core('./utils.js');
    let headers;
    const result = await readFileFromUrl('https://example.com/schema.json', {
        headers: [{ matches: 'example.com/**', name: 'X-Review', value: 'matched' }],
        customFetch: async (_url, options) => {
            headers = options.headers;
            return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
        },
    });
    assert.equal(headers['X-Review'], 'matched');
    assert.equal(result.body, '{}');
});
