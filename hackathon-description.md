# Alpaca AI Trading Agents Hackathon

These notes summarize the requirements used by Lexguard during development.
Verify the current event page and official rules before submitting:
https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon

## LLM Quick Reference

| Field | Requirement |
|---|---|
| Event | Alpaca AI Trading Agents Hackathon |
| Format | Online; 7 days; 28 August-4 September 2026 |
| Kickoff | Friday, 28 August 2026 at 5:00 PM Central European Summer Time |
| Prize pool | $6,000 |
| Project | Autonomous AI trading agent or trading app |
| Required API | Alpaca Trading API |
| Additional required integration | Alpaca MCP server **or** Alpaca CLI |
| Mandatory strategy component | Options trading |
| Trading mode | Alpaca paper trading only; no real capital |
| Final account | New, dedicated Alpaca paper-trading account |
| Account ID | Must be included in the final submission |
| Final account balance | Must start at $100,000 for the competition account |

## Objective

Build an autonomous AI trading agent on Alpaca. The agent must use Alpaca's Trading API, use either the Alpaca MCP server or CLI, and incorporate an options-trading strategy.

The project should be developed and tested in paper trading, which provides simulated funds with real market data. Nothing built for this hackathon should trade real money.

## Hard Requirements

A project is eligible only if it satisfies every requirement below.

1. **Autonomous AI agent:** The project must make and execute or manage trading decisions with an autonomous agent.
2. **Alpaca Trading API:** The project must use Alpaca's Trading API.
3. **MCP server or CLI:** The project must use at least one of Alpaca's MCP server or Alpaca CLI.
4. **Options trading:** The strategy must include options trading. A stocks-, ETFs-, or crypto-only strategy is insufficient.
5. **Paper trading:** Development, testing, and final evaluation occur in Alpaca paper trading.
6. **Fresh final account:** The submitted project must use a brand-new Alpaca paper-trading account created specifically for this hackathon.
7. **Account ID:** Include the final paper-trading account ID in the submission.
8. **Starting balance:** The competition account must start with $100,000.

## Account Rules

### Development

You may use any Alpaca paper account to explore the API, MCP server, and CLI, prototype the agent, and test strategies.

### Final judging

Create a new Alpaca paper-trading account dedicated to this hackathon. Projects using an existing or reused account are not eligible for judging.

The submitted account ID lets judges identify the agent's activity and evaluate P&L.

# Main Challenge and Strategy Directions

The official main challenge is **Options Alpha Agents**. Build an autonomous AI trading agent designed to generate P&L using Alpaca's trading platform. Develop a clear, testable trading strategy and demonstrate how your agent identifies opportunities, makes trading decisions, manages positions, and performs over the course of the competition. You may explore options, trading agents, portfolio income, or other approaches supported by Alpaca.

## Account requirements

**Use any paper account to start building:**
Sign up for Alpaca and open a paper trading account to explore the API, MCP
server, and CLI, prototype your agent, and test strategies. Use any paper
account you like during development.

**Submit with a new, fresh account:**
For your final submission, create a brand-new Alpaca paper trading account dedicated to this hackathon. Projects run on an existing or reused account will not be eligible for judging. This allows the judging team to identify your trading activity and evaluate your P&L performance.


### Additional requirements
1. Competition account starting balance must be set to $100,000.
2. One-page write-up covering your AI logic, risk gates, and Alpaca infrastructure implementation.

## Technology Reference

| Component | Purpose |
|---|---|
| Trading API | The programmable brokerage itself - the interface your app uses to place orders on US stocks, options, ETFs and crypto. |
| MCP server | Lets an AI assistant - Claude, Cursor, VS Code, ChatGPT - talk to Alpaca directly and execute through structured tools. This is the core of the hackathon theme. |
| Alpaca CLI | The same trading functions from a terminal command, with structured JSON output. Built for long-running agent sessions, cron jobs and CI, where MCP is heavier than needed. |
| Paper trading | Simulated funds with real market data. Free, no card required. Build and test without touching real money. |

## Required Submission Materials

### Project information

- Project title
- Short description
- Long description
- Technology tags
- Category tags

### Presentation

- Cover image
- Video presentation
- Slide presentation

### Application and access

- Public GitHub repository
- Demo application platform
- Application URL
- Final Alpaca paper-trading account ID
- One-page write-up covering AI logic, risk gates, and Alpaca infrastructure implementation


## Judging Criteria

### 1. P&L Performance (MOST IMPORTANT CRITERIA)

Judges evaluate the agent's paper-trading performance, including P&L and how effectively the strategy performs through actual trading activity.

Show identifiable activity from the submitted account and explain results beyond a single favorable trade or market condition.

### 2. Technology Implementation

Judges evaluate how effectively the project uses Alpaca's Trading API, MCP server, CLI, and other required technology to create an autonomous trading agent.

Make the required integrations and autonomous decision flow easy to verify.

### 3. Creativity & Originality

Judges evaluate the originality of the concept, trading strategy, agent behavior, and overall approach. Thoughtful, non-generic use of the technology is valued.

### 4. Presentation & Execution

Judges evaluate how clearly the project communicates the idea, demonstrates the agent in action, explains the trading thesis and agent reasoning, and presents results.

## Prizes

Total prize pool: **$6,000**.

- 1st place: $2,500
- 2nd place: $1,500
- 3rd place: $1,000


## Event Schedule

- 28 August, 5:00 PM CEST: Hackathon kickoff
- 28 August, 5:05 PM CEST: lablab.ai opening words
- 28 August, 5:10 PM CEST: Alpaca opening words
- 28 August, 5:15 PM CEST: Introduction to the challenge
- 28 August, 5:25 PM CEST: Hackathon guide
- 28 August, 6:00 PM CEST: Discord Q&A session
- 4 September, 5:00 PM CEST: End of submissions

## Final Compliance Checklist

- [ ] Autonomous AI trading agent
- [ ] Uses Alpaca Trading API
- [ ] Uses Alpaca MCP server or Alpaca CLI
- [ ] Incorporates options trading
- [ ] Uses paper trading only
- [ ] Uses a new, hackathon-dedicated paper account for final judging
- [ ] Includes the final paper-trading account ID
- [ ] Provides a public GitHub repository and application URL
- [ ] Includes title, short description, long description, and tags
- [ ] Includes cover image, video, and slides
- [ ] Explains strategy, agent reasoning, implementation, and results

## Disqualifying or Weak Patterns to Avoid

- A dashboard or tool with no autonomous decision loop.
- A strategy with no options component.
- Using the Trading API without either MCP server or CLI.
- Reusing an existing Alpaca account for final judging.
- Omitting the final paper-account ID.
- Showing only backtests rather than identifiable paper-trading activity.
- Failing to explain why the agent enters, manages, and exits trades.
