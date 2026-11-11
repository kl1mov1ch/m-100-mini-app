import { Button, Tag } from 'antd';
import { ExternalLink, RefreshCw } from 'lucide-react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { openExternalLink } from '../lib/telegram';

export function ObjectTableCard({ workspace }: { workspace: WorkspaceView }) {
	const { data, active, positions, checkingConnection, checkConnection, importRemote, busy } =
		workspace;
	if (!data || !active || data.project?.id !== active.id || data.config.source !== 'bitrix')
		return null;
	const config = data.config;
	const check = config.connection_check;
	const original = config.detail_url || config.public_url;
	return (
		<section className="object-table-card">
			<div className="object-table-card-top">
				<div>
					<b>{config.source_name}</b>
					<small>{positions.length} работ · Битрикс24.Диск</small>
				</div>
				<Tag color={config.has_webhook ? 'green' : 'gold'}>
					{config.has_webhook ? 'Подключена' : 'Только чтение'}
				</Tag>
			</div>
			{check && (
				<div
					className={
						'table-check-result ' +
						(!check.reachable ? 'failed' : check.issues.length ? 'has-issues' : 'success')
					}
				>
					<b>{check.message}</b>
					<span>{dayjs(check.checked_at).format('D MMMM, HH:mm')} · Минск</span>
					{check.reachable && check.issues.length > 0 && (
						<details className="table-check-issues">
							<summary>Замечания к данным: {check.issues.length}</summary>
							<ul>
								{check.issues.map((issue) => (
									<li key={issue.id}>
										<strong>{[issue.sheet, issue.cell].filter(Boolean).join(' · ')}</strong>
										<span>{issue.message}</span>
										{issue.position_name && <span>{issue.position_name}</span>}
										{issue.fix && <small>{issue.fix}</small>}
									</li>
								))}
							</ul>
							<Button size="small" onClick={importRemote} loading={busy}>
								Проверить и исправить
							</Button>
						</details>
					)}
				</div>
			)}
			<div className="object-table-card-actions">
				<Button
					loading={checkingConnection}
					icon={<RefreshCw size={15} />}
					onClick={checkConnection}
				>
					Проверить соединение
				</Button>
				{original && (
					<Button
						href={original}
						onClick={(event) => openExternalLink(event, original)}
						target="_blank"
						rel="noreferrer"
						icon={<ExternalLink size={15} />}
					>
						Открыть таблицу
					</Button>
				)}
			</div>
		</section>
	);
}
