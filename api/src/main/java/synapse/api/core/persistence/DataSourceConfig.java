package synapse.api.core.persistence;

import javax.sql.DataSource;

import org.springframework.boot.jdbc.DataSourceBuilder;
import org.springframework.boot.liquibase.autoconfigure.LiquibaseDataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import synapse.api.core.config.AppProperties;

/**
 * Duas conexões, com usuários diferentes em que o dono do schema migra e a aplicação
 * opera.
 */
@Configuration
public class DataSourceConfig {

	@Bean
	DataSource dataSource(AppProperties properties) {
		AppProperties.Postgres postgres = properties.postgres();
		return DataSourceBuilder.create()
			.url(postgres.jdbcUrl())
			.username(postgres.user())
			.password(postgres.password())
			.build();
	}

	/**
	 * Conexão do Liquibase. É a única que usa o dono do schema, e ela não vira o
	 * {@code DataSource} da aplicação: o pool de runtime é o bean acima.
	 */
	@Bean
	@LiquibaseDataSource
	DataSource liquibaseDataSource(AppProperties properties) {
		AppProperties.Postgres postgres = properties.postgres();
		return DataSourceBuilder.create()
			.url(postgres.jdbcUrl())
			.username(postgres.owner().user())
			.password(postgres.owner().password())
			.build();
	}

}
