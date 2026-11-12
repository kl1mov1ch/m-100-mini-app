export type TelegramInset = { top: number; bottom: number; left: number; right: number };

export type TelegramWebApp = {
	initData: string;
	version: string;
	viewportHeight: number;
	safeAreaInset?: TelegramInset;
	contentSafeAreaInset?: TelegramInset;
	ready(): void;
	expand(): void;
	isVersionAtLeast(version: string): boolean;
	setHeaderColor(color: string): void;
	setBackgroundColor(color: string): void;
	setBottomBarColor?(color: string): void;
	enableClosingConfirmation(): void;
	disableClosingConfirmation(): void;
	openLink(url: string): void;
	openTelegramLink?(url: string): void;
	downloadFile?(params: { url: string; file_name: string }): void;
	onEvent(event: string, handler: () => void): void;
	offEvent(event: string, handler: () => void): void;
	BackButton: {
		show(): void;
		hide(): void;
		onClick(handler: () => void): void;
		offClick(handler: () => void): void;
	};
	HapticFeedback?: { notificationOccurred(type: string): void };
};
