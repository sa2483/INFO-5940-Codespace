Reflection Document 

1. What did you learn from implementing a multi-agent workflow?

Building the multi-agent workflow helped me understand how different agents can work together to make a system more reliable and realistic. The Planner Agent focused on creating the itinerary, while the Reviewer Agent checked details like travel times and museum hours using live data from Tavily. This setup worked really well because each agent had a clear role — one was creative, and the other was careful and factual. Seeing the Reviewer automatically verify information made the project imitate/ feel close to how people collaborate in real life.

2. Challenges faced and how you addressed them? 

I faced a lot of challenges with the setup. At first, the Tavily API key was not being read inside my Codespace, so the Reviewer could not do live searches. I fixed this by adding the key to the remoteEnv section of .devcontainer/devcontainer.json and rebuilding the container. But even after several tries, the Reviewer was not utilising the internet search tool until I changed the prompt to: 

**You MUST use the `internet_search` tool whenever any fact-checking could materially change the itinerary (e.g., museum hours, ticket prices, transit times).** Before this, the prompt only said “you are allowed to use the internet_search tool”, which made the model treat it as optional rather than necessary. This showed me how important clear instructions are when working with large language models and it was very rewarding to watch the Reviewer finally be able to call the search tool and see the validation process update in real time. 

3. Any creative ideas, variations, or design choices (e.g., persona roles, prompt design)?

I experimented with giving the agents different “personalities” — the Planner was more curious and imaginative, while the Reviewer was factual and precise. This contrast made their interaction feel more human-like. I also designed the Reviewer’s instructions to produce a clear, three-part output (Validation Summary, Delta List, Revised Itinerary), which made it easier to evaluate changes. If I had more time, I would add a third Coordinator Agent to handle timing and reduce repeated searches.

Overall, I learned that building a multi-agent system requires technical setup (APIs, environment variables) and design thinking (clear prompts, roles, and feedback). You have to think like a product designer and an engineer. This was a wonderful learning experience and I thoroughly enjoyed building this multi-agent system for Assignment 2.

External tools used: ChatGPT (for debugging help, prompt writing, code support) was used for the purposes of learning and improving the workflow.
