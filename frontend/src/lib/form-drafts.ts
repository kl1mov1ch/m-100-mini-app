const prefix = 'm100-form-draft:';
const week = 7 * 24 * 60 * 60 * 1000;

function load<T>(key: string): { value: T; expiresAt: number } | undefined {
	try {
		const raw = localStorage.getItem(prefix + key);
		if (!raw) return;
		const draft = JSON.parse(raw);
		if (typeof draft?.expiresAt !== 'number' || draft.expiresAt <= Date.now()) {
			localStorage.removeItem(prefix + key);
			return;
		}
		return draft;
	} catch {
		return;
	}
}

export function readFormDraft<T>(key: string) {
	return load<T>(key)?.value;
}

export function writeFormDraft(key: string, value: unknown) {
	try {
		const previous = load<unknown>(key);
		if (previous && JSON.stringify(previous.value) === JSON.stringify(value)) return;
		localStorage.setItem(prefix + key, JSON.stringify({ value, expiresAt: Date.now() + week }));
	} catch {
		// Forms remain usable when storage is disabled or full.
	}
}

export function removeFormDraft(key: string) {
	try {
		localStorage.removeItem(prefix + key);
	} catch {
		// Forms remain usable when storage is disabled.
	}
}

export function pruneFormDrafts() {
	try {
		for (let i = localStorage.length - 1; i >= 0; i--) {
			const key = localStorage.key(i);
			if (key?.startsWith(prefix)) load(key.slice(prefix.length));
		}
	} catch {
		// Storage can be disabled in the browser.
	}
}
