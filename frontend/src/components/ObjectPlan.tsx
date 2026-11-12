import { Alert, Empty, Modal, Spin } from 'antd';
import { useEffect, useState } from 'react';
import { request } from '../lib/api';
import { Money } from '../lib/format';
import { formatVolume } from '../lib/position-volume';

type Plan = {
	amount: number;
	groups: {
		name: string;
		amount: number;
		rows: { id: string; name: string; quantity: number; unit: string; amount: number }[];
	}[];
	steps: string[];
};

export function ObjectPlan({ project, close }: { project: string; close: () => void }) {
	const [plan, setPlan] = useState<Plan | null>(null);
	const [error, setError] = useState('');
	useEffect(() => {
		const controller = new AbortController();
		request<Plan>('/object/plan', undefined, project, controller.signal)
			.then((result) => {
				if (!controller.signal.aborted) setPlan(result);
			})
			.catch((failure) => {
				if (!controller.signal.aborted) setError((failure as Error).message);
			});
		return () => controller.abort();
	}, [project]);
	return (
		<Modal open title="План по остаткам сметы" onCancel={close} footer={null} width={650}>
			<div className="position-history">
				{error && <Alert type="warning" showIcon message={error} />}
				{!error && !plan && <Spin />}
				{plan && !plan.groups.length && (
					<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="В смете нет оставшихся работ" />
				)}
				{!!plan?.groups.length && (
					<>
						<p>
							Осталось работ на{' '}
							<b>
								<Money value={plan.amount} />
							</b>
						</p>
						{plan.steps.length > 0 && (
							<section>
								<b>Порядок работ от ИИ</b>
								<ol>
									{plan.steps.map((step) => (
										<li key={step}>{step}</li>
									))}
								</ol>
							</section>
						)}
						{plan.groups.map((group) => (
							<details key={group.name}>
								<summary>
									{group.name} · <Money value={group.amount} />
								</summary>
								<ul>
									{group.rows.map((row) => (
										<li key={row.id}>
											{row.name} · {formatVolume(row.quantity, row.unit)} ·{' '}
											<Money value={row.amount} />
										</li>
									))}
								</ul>
							</details>
						))}
					</>
				)}
			</div>
		</Modal>
	);
}
