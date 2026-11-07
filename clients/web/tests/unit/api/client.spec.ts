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
        vi.spyOn(localStorage, "removeItem").mockImplementation((key) => {
            storage.delete(key);
        });
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

    it("requests only the selected library page with a bounded limit", async () => {
        const requests: URL[] = [];
        vi.stubGlobal(
            "fetch",
            vi.fn(async (request: Request) => {
                requests.push(new URL(request.url));
                return Response.json([{ id: 49 }]);
            }),
        );
        const { libraries } = await import("@/api/client");
        const items = await libraries.getLibraryItems(1, 48, 49);
        expect(items).toHaveLength(1);
        expect(requests).toHaveLength(1);
        expect(requests[0].searchParams.get("skip")).toBe("48");
        expect(requests[0].searchParams.get("limit")).toBe("49");
    });
    it("preserves credentials on a temporary refresh outage", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (input) =>
                typeof input === "string" ? new Response(null, { status: 503 }) : new Response(null, { status: 401 }),
            ),
        );
        const { client, getAccessToken, getRefreshToken } = await import("@/api/client");
        await expect(client.GET("/api/v1/users/me")).rejects.toThrow("Token refresh failed");
        expect(getAccessToken()).toBe("expired");
        expect(getRefreshToken()).toBe("refresh");
    });
    it("revokes local credentials and emits one navigation event for an expired session", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response(null, { status: 401 })),
        );
        const expired = vi.fn();
        window.addEventListener("ferelix:session-expired", expired);
        const { client, getAccessToken } = await import("@/api/client");
        await expect(client.GET("/api/v1/users/me")).rejects.toThrow("Token refresh failed");
        expect(getAccessToken()).toBeNull();
        expect(expired).toHaveBeenCalledOnce();
        window.removeEventListener("ferelix:session-expired", expired);
    });
    it.each([401, 503])("preserves login HTTP status %i for useful user feedback", async (status) => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response(null, { status })),
        );
        const { auth } = await import("@/api/client");
        await expect(auth.login("user", "password")).rejects.toMatchObject({ status });
    });
    it("clears local credentials before waiting for logout network completion", async () => {
        let complete: (response: Response) => void = () => {};
        vi.stubGlobal(
            "fetch",
            vi.fn(
                () =>
                    new Promise<Response>((resolve) => {
                        complete = resolve;
                    }),
            ),
        );
        const { auth, getAccessToken, getRefreshToken } = await import("@/api/client");
        const pending = auth.logout();
        expect(getAccessToken()).toBeNull();
        expect(getRefreshToken()).toBeNull();
        await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());
        complete(new Response(null, { status: 204 }));
        await pending;
    });
    it("uses session grants for native and HLS URLs independently of the JWT", async () => {
        const { mediaSessionUrl, saveTokens } = await import("@/api/client");
        const grant = { sessionId: "session-1", token: "media-grant" };
        const first = mediaSessionUrl("/api/v1/media/1/stream?api_key=expired&x=1", grant);
        saveTokens("new-api-token", "next-refresh");
        expect(mediaSessionUrl("/api/v1/media/1/stream?api_key=other&x=1", grant)).toBe(first);
        const query = new URL(first, window.location.origin).searchParams;
        expect(query.get("api_key")).toBeNull();
        expect(query.get("media_token")).toBe("media-grant");
        expect(query.get("session_id")).toBe("session-1");
        expect(() => mediaSessionUrl("https://external.test/video", grant)).toThrow("Invalid media origin");
        expect(() => mediaSessionUrl("/video")).toThrow("No active playback session");
    });

    it("does not resurrect tokens when refresh finishes after logout", async () => {
        let complete: (response: Response) => void = () => {};
        vi.stubGlobal(
            "fetch",
            vi.fn(async (input) =>
                typeof input === "string"
                    ? new Promise<Response>((resolve) => {
                          complete = resolve;
                      })
                    : new Response(null, { status: 401 }),
            ),
        );
        const { client, clearTokens, getAccessToken } = await import("@/api/client");
        const pending = client.GET("/api/v1/users/me");
        const failed = expect(pending).rejects.toThrow("Session changed during refresh");
        await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
        clearTokens();
        complete(Response.json({ access_token: "late", refresh_token: "late-refresh" }));
        await failed;
        expect(getAccessToken()).toBeNull();
    });
    it("never replays account A's delayed mutation with account B's credentials", async () => {
        let complete: (response: Response) => void = () => {};
        vi.stubGlobal(
            "fetch",
            vi.fn(
                () =>
                    new Promise<Response>((resolve) => {
                        complete = resolve;
                    }),
            ),
        );
        const { client, clearTokens, saveTokens } = await import("@/api/client");
        const pending = client.PATCH("/api/v1/users/me", { body: { username: "A-new-name" } });
        const failed = expect(pending).rejects.toThrow("Session changed during request");
        await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());
        clearTokens();
        saveTokens("account-B", "refresh-B");
        complete(new Response(null, { status: 401 }));
        await failed;
        expect(fetch).toHaveBeenCalledOnce();
    });
});
