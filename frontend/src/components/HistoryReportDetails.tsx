import { Alert, Spin } from 'antd';
import { useEffect, useState } from 'react';
import { request } from '../lib/api';
import { Money, nf, unit } from '../lib/format';
import type { Data, Report } from '../types';
import { CompactWorkEditor } from './CompactRow';

export function HistoryReportDetails({ project, date }: { project: string; date: string }) {
	const [data, setData] = useState<{ report: Report; positions: Data['positions'] }>();
	const [error, setError] = useState('');
	useEffect(() => {
		const controller = new AbortController();
		Promise.all([
			request<Report>('/report/' + date, undefined, project, controller.signal),
			request<Data>('/bootstrap', undefined, project, controller.signal),
		])
			.then(([report, bootstrap]) => setData({ report, positions: bootstrap.positions }))
			.catch((failure) => {
				if (!controller.signal.aborted) setError(failure.message);
			});
		return () => controller.abort();
	}, [project, date]);
	if (error) return <Alert type="error" message={error} />;
	if (!data) return <Spin size="small" />;
	return (
		<div className="history-report-works">
			<h3>Работы в этом отчёте · {data.report.lines.length}</h3>
			<div className="compact-list">
				{data.report.lines.map((line, index) => {
					const position = data.positions.find((item) => item.id === line.item_id);
					return (
						<CompactWorkEditor
							key={line.item_id || index}
							title={position?.name || line.raw || 'Работа'}
							description={`${nf.format(line.quantity || 0)} ${unit(position?.unit || line.unit || 'ед.')}`}
							value={position ? <Money value={position.rate * (line.quantity || 0)} /> : '—'}
						>
							<dl className="report-detail-summary">
								<div>
									<dt>За день</dt>
									<dd>
										{nf.format(line.quantity || 0)} {unit(position?.unit || line.unit || 'ед.')}
									</dd>
								</div>
								{position && (
									<>
										<div>
											<dt>Расценка сейчас</dt>
											<dd>
												<Money value={position.rate} /> / {unit(position.unit)}
											</dd>
										</div>
										<div>
											<dt>По смете</dt>
											<dd>
												{nf.format(position.planned)} {unit(position.unit)}
											</dd>
										</div>
									</>
								)}
							</dl>
						</CompactWorkEditor>
					);
				})}
			</div>
		</div>
	);
}
