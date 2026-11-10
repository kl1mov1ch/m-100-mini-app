import { Button } from 'antd';
import { ExternalLink, FileSpreadsheet, ShieldCheck } from 'lucide-react';
import minskDate from '../lib/date';
import type { Config } from '../types';
import { openExternalLink } from '../lib/telegram';

export function LinkedTable({
	config,
	positions,
	onSettings,
}: {
	config: Config;
	positions: number;
	onSettings: () => void;
}) {
	return (
		<section className="linked-table-card">
			<span className="linked-table-icon">
				<FileSpreadsheet size={22} />
			</span>
			<div className="linked-table-info">
				<b>{config.source_name}</b>
				<span>
					{config.source === 'bitrix' ? 'Битрикс24.Диск' : 'Загруженная таблица'} · {positions}{' '}
					работ
				</span>
				{config.last_import && (
					<small>Прочитано {minskDate(config.last_import).format('D MMMM, HH:mm')} · Минск</small>
				)}
				<div className="linked-table-status">
					<ShieldCheck size={13} />
					{config.has_webhook && config.source === 'bitrix'
						? 'Чтение и автоотправка подключены'
						: config.source === 'bitrix'
							? 'Чтение подключено · для записи нужен вебхук'
							: 'Файл готов к работе'}
				</div>
			</div>
			<div className="linked-table-actions">
				{config.public_url && (
					<Button
						aria-label="Открыть связанную таблицу"
						type="text"
						href={config.public_url}
						onClick={(event) => openExternalLink(event, config.public_url)}
						target="_blank"
						rel="noreferrer"
						icon={<ExternalLink size={16} />}
					/>
				)}
				<Button size="small" onClick={onSettings}>
					Настроить
				</Button>
			</div>
		</section>
	);
}
