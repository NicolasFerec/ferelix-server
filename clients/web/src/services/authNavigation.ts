/** Keep post-login navigation inside this application, without auth loops. */
export function safeReturnTo(value: unknown): string {
    if (
        typeof value !== "string" ||
        !value.startsWith("/") ||
        value.startsWith("//") ||
        value.includes("\\") ||
        [...value].some((character) => character.charCodeAt(0) < 32)
    )
        return "/";
    const destination = new URL(value, "https://ferelix.invalid");
    if (destination.origin !== "https://ferelix.invalid" || /^\/(login|setup)(\/|$)/.test(destination.pathname))
        return "/";
    return `${destination.pathname}${destination.search}${destination.hash}`;
}

export const SESSION_EXPIRED_EVENT = "ferelix:session-expired";
