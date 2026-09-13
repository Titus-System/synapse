package synapse.api.core.persistence;

import javax.sql.DataSource;

import org.springframework.boot.jdbc.DataSourceBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import synapse.api.core.config.AppProperties;

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

}
