type IconName =
	| 'calendar'
	| 'check'
	| 'chevron-down'
	| 'chevron-left'
	| 'chevron-right'
	| 'close'
	| 'folder'
	| 'report'
	| 'search';

export function TelegramIcon({ name, size = 24 }: { name: IconName; size?: number }) {
	return (
		<svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
			<use href={`/brand/telegram-icons.svg#${name}`} stroke="none" />
		</svg>
	);
}
