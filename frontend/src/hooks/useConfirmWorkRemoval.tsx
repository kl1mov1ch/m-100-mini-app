import { Alert, App } from 'antd';
import { TriangleAlert } from 'lucide-react';
import { nf, unit } from '../lib/format';

export function useConfirmWorkRemoval() {
	const { modal } = App.useApp();
	return (
		work: { name: string; quantity?: number | null; unit?: string; saved?: boolean },
		remove: () => void,
	) => {
		modal.confirm({
			title: 'Убрать работу из отчёта?',
			icon: <TriangleAlert color="#a66b00" size={22} />,
			okText: 'Убрать работу',
			cancelText: 'Оставить',
			okButtonProps: { danger: true },
			content: (
				<Alert
					type="warning"
					message={work.name}
					description={
						<>
							{work.quantity != null && (
								<p>
									Объём {nf.format(work.quantity)} {unit(work.unit || 'ед.')}
								</p>
							)}
							<p>
								{work.saved
									? 'Сумма и доля на человека пересчитаются. В сохранённом отчёте объём изменится после подтверждения.'
									: 'Работа исчезнет из черновика. Сумма и доля на человека пересчитаются.'}
							</p>
						</>
					}
				/>
			),
			onOk: remove,
		});
	};
}
