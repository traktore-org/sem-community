/** (#1083) downloadBase64 — base64 to a saved file, URL revoked after. */
import { test } from 'node:test';
import assert from 'node:assert';
import { downloadBase64 } from '../src/util/download.js';

function stubDom() {
    const made = [];
    const revoked = [];
    let clicked = null;
    const body = { children: [], appendChild(el) { this.children.push(el); } };
    globalThis.document = {
        body,
        createElement(tag) {
            const el = {
                tag, href: '', download: '',
                click() { clicked = { href: this.href, download: this.download }; },
                remove() { body.children = body.children.filter(c => c !== el); },
            };
            return el;
        },
    };
    const realURL = globalThis.URL;
    globalThis.URL = Object.assign(function () {}, realURL, {
        createObjectURL(blob) { made.push(blob); return 'blob:sem/1'; },
        revokeObjectURL(u) { revoked.push(u); },
    });
    const realTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn) => { fn(); return 0; };
    return {
        made, revoked, body, clicked: () => clicked,
        restore() { globalThis.URL = realURL; globalThis.setTimeout = realTimeout; delete globalThis.document; },
    };
}

test('bytes, name and type reach the saved file; the URL is revoked', async () => {
    const dom = stubDom();
    try {
        const bytes = [0x50, 0x4b, 0x03, 0x04, 0x00, 0xff];
        const b64 = Buffer.from(bytes).toString('base64');
        const mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
        const blob = downloadBase64('sem-sessions-2026-10-14.xlsx', b64, mime);
        assert.equal(blob.type, mime);
        assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], bytes);
        assert.deepEqual(dom.clicked(), { href: 'blob:sem/1', download: 'sem-sessions-2026-10-14.xlsx' });
        assert.equal(dom.made[0], blob);
        assert.deepEqual(dom.revoked, ['blob:sem/1']);
        assert.equal(dom.body.children.length, 0);
    } finally {
        dom.restore();
    }
});

test('no type given saves as plain bytes', () => {
    const dom = stubDom();
    try {
        const blob = downloadBase64('x.bin', Buffer.from('hi').toString('base64'));
        assert.equal(blob.type, 'application/octet-stream');
    } finally {
        dom.restore();
    }
});
