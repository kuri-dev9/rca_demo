# Ollama Chat Demo 시스템 구성 현황 및 기능 명세서

## 문서 목록

| # | 문서 | 파일명 | 설명 |
|---|------|--------|------|
| 01 | 시스템 개요 | [01_시스템_개요.md](01_시스템_개요.md) | 시스템 목적, 범위, 기술 스택 요약 |
| 02 | 시스템 구성도 | [02_시스템_구성도.md](02_시스템_구성도.md) | 전체 아키텍처, 계층별 역할, 통신 흐름 |
| 03 | 모듈별 상세기능 | [03_모듈별_상세기능.md](03_모듈별_상세기능.md) | 백엔드 라우터/모듈 및 프론트엔드 컴포넌트 상세 |
| 04 | 인터페이스 정의 | [04_인터페이스_정의.md](04_인터페이스_정의.md) | REST API, SSE 스트리밍, 외부 연동 스펙 |
| 05 | 데이터베이스 설계 | [05_데이터베이스_설계.md](05_데이터베이스_설계.md) | 테이블 구조, 관계, ORM 모델 매핑 |
| 06 | 프론트엔드 API 스펙 | [06_프론트엔드_API_스펙.md](06_프론트엔드_API_스펙.md) | 프론트엔드 컴포넌트별 Backend API 호출 상세 |

## 다이어그램 (PlantUML)

| 다이어그램 | 파일명 | 설명 |
|-----------|--------|------|
| 시스템 구성도 | [system-architecture.puml](diagrams/system-architecture.puml) | 전체 계층별 아키텍처 컴포넌트 다이어그램 |
| 채팅 처리 흐름 | [network-flow.puml](diagrams/network-flow.puml) | 채팅 요청의 전체 처리 흐름 시퀀스 다이어그램 |
| DB ERD | [db-erd.puml](diagrams/db-erd.puml) | 데이터베이스 엔티티 관계 다이어그램 |
| RAG 파이프라인 | [rag-pipeline-flow.puml](diagrams/rag-pipeline-flow.puml) | 2-Stage RAG 파이프라인 활동 다이어그램 |

## PlantUML 렌더링

`.puml` 파일은 아래 방법으로 이미지를 생성할 수 있습니다:

```bash
# PlantUML JAR 사용
java -jar plantuml.jar diagrams/*.puml

# VS Code PlantUML Extension
# IntelliJ PlantUML Integration Plugin
```
