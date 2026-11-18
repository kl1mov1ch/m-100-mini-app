import { App, Modal, type ModalProps } from 'antd';
import { useRef, type MouseEvent, type PointerEvent, type ReactNode } from 'react';

function SheetHandle({
	children,
	close,
}: {
	children: ReactNode;
	close: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
	const sheet = useRef<HTMLDivElement>(null);
	const gesture = useRef<{ pointer: number; start: number } | null>(null);

	function finish(event: PointerEvent<HTMLButtonElement>, dismiss: boolean) {
		if (gesture.current?.pointer !== event.pointerId) return;
		const distance = event.clientY - gesture.current.start;
		gesture.current = null;
		sheet.current?.style.removeProperty('transform');
		if (dismiss && distance >= 40) close(event);
	}

	return (
		<div className="sheet-modal-frame" ref={sheet}>
			{children}
			<button
				className="sheet-modal-handle"
				type="button"
				aria-label="Закрыть окно"
				onClick={(event) => {
					if (event.detail === 0) close(event);
				}}
				onPointerDown={(event) => {
					if (!event.isPrimary || event.button !== 0) return;
					event.currentTarget.setPointerCapture(event.pointerId);
					gesture.current = { pointer: event.pointerId, start: event.clientY };
				}}
				onPointerMove={(event) => {
					if (gesture.current?.pointer !== event.pointerId) return;
					const distance = Math.max(0, event.clientY - gesture.current.start);
					if (sheet.current) sheet.current.style.transform = `translateY(${distance}px)`;
				}}
				onPointerUp={(event) => finish(event, true)}
				onPointerCancel={(event) => finish(event, false)}
				onLostPointerCapture={(event) => finish(event, false)}
			/>
		</div>
	);
}

export function SheetModal({ modalRender, onCancel, closable, ...props }: ModalProps) {
	return (
		<Modal
			getContainer={() => document.getElementById('miniapp-surface') ?? document.body}
			{...props}
			className={['journal-sheet', props.className].filter(Boolean).join(' ')}
			onCancel={onCancel}
			closable={closable}
			modalRender={(node) => {
				const content = modalRender ? modalRender(node) : node;
				return onCancel &&
					closable !== false &&
					!(typeof closable === 'object' && closable.disabled) ? (
					<SheetHandle close={onCancel}>{content}</SheetHandle>
				) : (
					content
				);
			}}
		/>
	);
}

type Confirm = ReturnType<typeof App.useApp>['modal']['confirm'];

export function confirmSheet(modal: { confirm: Confirm }, options: Parameters<Confirm>[0]) {
	return modal.confirm({
		getContainer: () => document.getElementById('miniapp-surface') ?? document.body,
		closable: true,
		...options,
		className: ['journal-sheet', options.className].filter(Boolean).join(' '),
		modalRender: (node) => (
			<SheetHandle
				close={(event) =>
					event.currentTarget
						.closest('.ant-modal')
						?.querySelector<HTMLButtonElement>('.ant-modal-close')
						?.click()
				}
			>
				{options.modalRender ? options.modalRender(node) : node}
			</SheetHandle>
		),
	});
}
