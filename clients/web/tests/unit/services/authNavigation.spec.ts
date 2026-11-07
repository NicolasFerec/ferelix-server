import { expect, it } from "vitest";
import { safeReturnTo } from "@/services/authNavigation";

it.each([
    "https://attacker.invalid",
    "//attacker.invalid",
    "/\\attacker.invalid",
    "/login?redirect=/play/1",
    "/setup",
    "\n/play/1",
    null,
    ["/play/1"],
])("rejects unsafe or looping login destinations: %s", (value) => {
    expect(safeReturnTo(value)).toBe("/");
});
it("preserves a local deep link and its track selections", () => {
    expect(safeReturnTo("/play/17?audio=2&video=0#position")).toBe("/play/17?audio=2&video=0#position");
});
