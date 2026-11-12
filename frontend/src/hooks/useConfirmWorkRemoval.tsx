import { App } from 'antd';
import { nf, unit } from '../lib/format';

export function useConfirmWorkRemoval() {
	const { modal } = App.useApp();
	return (
		work: { name: string; quantity?: number | null; unit?: string; saved?: boolean },
		remove: () => void,
	) => {
		modal.confirm({
			title: 'Убрать работу из отчёта?',
			icon: null,
			className: 'action-confirm-sheet',
			okText: 'Убрать работу',
			cancelText: 'Оставить',
			okButtonProps: { danger: true },
			content: (
				<div className="action-confirm-content">
					<div className="action-confirm-item">
						<strong>{work.name}</strong>
						{work.quantity != null && (
							<span>
								{nf.format(work.quantity)} {unit(work.unit || 'ед.')}
							</span>
						)}
					</div>
					<p>
						{work.saved
							? 'Работа будет убрана из сохранённого отчёта после подтверждения изменений.'
							: 'Работа будет убрана из черновика.'}{' '}
						Сумма и доля на человека пересчитаются.
					</p>
				</div>
			),
			onOk: remove,
		});
	};
}
