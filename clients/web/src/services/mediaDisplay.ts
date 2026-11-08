export interface MediaTitleInfo {
    title: string;
    year: string | null;
}

export function getMediaTitleInfo(fileName: string): MediaTitleInfo {
    const stem = stripExtension(fileName);
    return splitTitleAndYear(stem);
}

function stripExtension(fileName: string): string {
    const lastDot = fileName.lastIndexOf(".");
    return lastDot > 0 ? fileName.substring(0, lastDot) : fileName;
}

function cleanTitle(value: string): string {
    return value
        .replace(/[._]+/g, " ")
        .replace(/[\s-]+$/g, "")
        .replace(/\s{2,}/g, " ")
        .trim();
}

function splitTitleAndYear(stem: string): MediaTitleInfo {
    const bracketedYear = stem.match(/[[(]((?:19|20)\d{2})[\])]/);
    if (bracketedYear?.index !== undefined) {
        const title = cleanTitle(stem.slice(0, bracketedYear.index));
        if (title) {
            return { title, year: bracketedYear[1] };
        }
    }

    const separatedYearPattern = /(?:^|[\s._-])((?:19|20)\d{2})(?=$|[\s._-])/g;
    let separatedYear = separatedYearPattern.exec(stem);
    while (separatedYear) {
        if (separatedYear.index > 0) {
            const title = cleanTitle(stem.slice(0, separatedYear.index));
            if (title) {
                return { title, year: separatedYear[1] };
            }
        }
        separatedYear = separatedYearPattern.exec(stem);
    }

    return { title: cleanTitle(stem), year: null };
}

/** Provider dates have no time zone; format them without shifting the calendar day. */
export function formatReleaseDate(value: string, locale: string): string {
    const date = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(date.valueOf())
        ? value
        : new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(date);
}
