import { App, Segmented } from 'antd';
import { useRef, type TouchEvent } from 'react';
import type { WorkspaceView } from '../App';
import type { ViewMode } from '../types';

export function RoleSwitch({
	workspace,
	unsaved = false,
}: {
	workspace: WorkspaceView;
	unsaved?: boolean;
}) {
	const { modal } = App.useApp();
	const { session, switchingRole, changeViewMode, report, dirty, freeText, busy } = workspace;
	const touchStart = useRef<{ x: number; y: number } | null>(null);
	const confirming = useRef(false);

	const selectMode = (mode: ViewMode) => {
		if (mode === session.view_mode || switchingRole || busy || confirming.current) return;
		if ((report && dirty) || freeText.trim() || unsaved) {
			confirming.current = true;
			modal.confirm({
				title: 'Переключить режим?',
				content: 'Несохранённые изменения в текущем режиме будут сброшены.',
				okText: 'Переключить',
				cancelText: 'Остаться',
				afterClose: () => {
					confirming.current = false;
				},
				onOk: () => changeViewMode(mode),
			});
		} else {
			void changeViewMode(mode);
		}
	};
	const finishSwipe = (event: TouchEvent) => {
		const start = touchStart.current;
		touchStart.current = null;
		const end = event.changedTouches[0];
		if (!start || !end) return;
		const horizontal = end.clientX - start.x;
		const vertical = end.clientY - start.y;
		if (Math.abs(horizontal) < 38 || Math.abs(horizontal) < Math.abs(vertical) * 1.5) return;
		selectMode(horizontal > 0 ? 'master' : 'admin');
	};
	if (session.mode !== 'development' || !session.can_switch_role) return null;
	return (
		<div
			className="role-switch"
			onTouchStart={(event) => {
				const touch = event.touches[0];
				touchStart.current =
					event.touches.length === 1 ? { x: touch.clientX, y: touch.clientY } : null;
			}}
			onTouchEnd={finishSwipe}
			onTouchCancel={() => {
				touchStart.current = null;
			}}
		>
			<Segmented<ViewMode>
				block
				aria-label="Режим работы"
				disabled={switchingRole || busy}
				value={session.view_mode}
				options={[
					{ value: 'admin', label: 'Администратор' },
					{ value: 'master', label: 'Мастер' },
				]}
				onChange={selectMode}
			/>
		</div>
	);
}
