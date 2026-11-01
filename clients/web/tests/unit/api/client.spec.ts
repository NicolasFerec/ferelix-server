import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const NativeRequest = globalThis.Request;

describe("authentication retries", () => {
    beforeEach(() => {
        vi.resetModules();
        const storage = new Map([
            ["auth_access_token", "expired"],
            ["auth_refresh_token", "refresh"],
        ]);
        vi.spyOn(localStorage, "getItem").mockImplementation((key) => storage.get(key) ?? null);
        vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
            storage.set(key, value);
        });
        vi.stubGlobal(
            "Request",
            class extends NativeRequest {
                constructor(input: RequestInfo | URL, init?: RequestInit) {
                    super(typeof input === "string" ? new URL(input, "http://localhost") : input, init);
                }
            },
        );
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("replays a consumed PATCH body after refreshing the token", async () => {
        const bodies: string[] = [];
        vi.stubGlobal(
            "fetch",
            vi.fn(async (input: RequestInfo | URL) => {
                if (typeof input === "string") {
                    return Response.json({ access_token: "new", refresh_token: "next" });
                }
                const request = input as Request;
                bodies.push(await request.text());
                return request.headers.get("Authorization") === "Bearer new"
                    ? Response.json({ language: "fr" })
                    : new Response(null, { status: 401 });
            }),
        );
        const { client } = await import("@/api/client");
        const result = await client.PATCH("/api/v1/users/me", { body: { language: "fr" } });
        expect(result.response.status).toBe(200);
        expect(bodies).toEqual(['{"language":"fr"}', '{"language":"fr"}']);
    });

    it("rejects all concurrent requests when the shared refresh fails", async () => {
        let rejectRefresh: (error: Error) => void = () => {};
        const pendingRefresh = new Promise<Response>((_resolve, reject) => {
            rejectRefresh = reject;
        });
        let refreshCalls = 0;
        vi.stubGlobal(
            "fetch",
            vi.fn(async (input: RequestInfo | URL) => {
                if (typeof input === "string") {
                    refreshCalls++;
                    return pendingRefresh;
                }
                return new Response(null, { status: 401 });
            }),
        );
        const { client } = await import("@/api/client");
        const completed = Promise.allSettled([client.GET("/api/v1/users/me"), client.GET("/api/v1/users/me")]);
        await vi.waitFor(() => expect(refreshCalls).toBe(1));
        rejectRefresh(new Error("network unavailable"));
        const results = await completed;
        expect(results.map((result) => result.status)).toEqual(["rejected", "rejected"]);
    });

    it("loads library media beyond the first page", async () => {
        const skips: number[] = [];
        vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
            const skip = Number(new URL(request.url).searchParams.get("skip"));
            skips.push(skip);
            return Response.json(Array.from({ length: skip === 0 ? 100 : 1 }, (_, index) => ({ id: skip + index })));
        }));
        const { libraries } = await import("@/api/client");
        const items = await libraries.getAllLibraryItems(1);
        expect(items).toHaveLength(101);
        expect(skips).toEqual([0, 100]);
    });
});
